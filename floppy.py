#!/bin/env python3
from greaseweazle.tools import util
from greaseweazle import error
from greaseweazle import usb as USB
from greaseweazle.flux import Flux, HasFlux
from greaseweazle.codec import codec
from greaseweazle.codec.codec import DiskDef_File
from greaseweazle.image import image
from greaseweazle import track
import logging
from pydantic import BaseModel, Field, field_validator
import sys
import yaml


drive_params = {
    '5.25DD': {'tracks': 40, 'heads': 2},
    '5.25HD': {'tracks': 80, 'heads': 2},
    '3.5DD': {'tracks': 80, 'heads': 2},
    '3.5HD': {'tracks': 80, 'heads': 2}
}


class FloppyReaderConfig(BaseModel):
    """
    Structure of the configuration file
    """
    class GreaseWeazleConfig(BaseModel):
        port: str = Field(default="auto")
        drives: dict[str | int, str] = Field(default_factory=dict)

        @field_validator('drives')
        @classmethod
        def check_drives(cls, value: dict):
            new = {}
            for k, v in value.items():
                nk = str(k).upper()
                if nk not in ('0', '1', '2', 'A', 'B'):
                    raise ValueError("Drive letter must be 0, 1, 2, A, or B")
                nv = v.upper()
                if nv not in drive_params.keys(): 
                    raise ValueError(f"Drive Type must be one of: {list(drive_params.keys())}")
                new[nk] = nv            
            return new

    greaseweazle: GreaseWeazleConfig
    
    formats: dict[str, list[list[str] | str]]

    @field_validator('formats')
    @classmethod
    def check_formats(cls, value: dict):
        new = {}
        for k, v in value.items():
            nk = k.upper()
            if nk not in drive_params.keys():
                raise ValueError(f"Drive Type must be one of: {list(drive_params.keys())}")
            nv = []
            for x in v:
                if isinstance(x, list):
                    nv.extend(x)
                else:
                    nv.append(x)
            # make sure each of the formats are actually supported by the greaseweazle
            all_formats = codec.get_all_formats('', DiskDef_File(None))
            for x in nv:
                if x not in all_formats:
                    raise ValueError(f"Format {x} not supported")
        
            new[nk] = nv
        return new


class FloppyReader:
    def __init__(self, config):
        with open(config) as f:
            self.config = FloppyReaderConfig(**yaml.safe_load(f))

        # connect to the greaseweazle        
        port = self.config.greaseweazle.port
        self.gw: USB.Unit  = util.usb_open(None if port=='auto' else port)

        # get the drive devices for everything..
        self.drives: dict[str, util.Drive] = {}
        for d, t in self.config.greaseweazle.drives.items():
            self.drives[d] = {
                'type': t,
                **drive_params[t],
                'drive': util.Drive()(d)
            }


    def use_drive(self, function, drive: str, motor: bool = True, *args, **kwargs):
        """Select the drive, optionally turn on the motor, and then run the function
        The function will be called with these arguments:
        function(the greaseweazle, the drive, *args, **kwargs)        
        """
        if drive not in self.drives:
            raise FileNotFoundError("This drive is not configured")
        
        drv: util.Drive = self.drives[drive]['drive']        
        self.gw.set_bus_type(drv.bus.value)        
        res = None
        try:
            self.gw.drive_select(drv.unit_id)
            self.gw.drive_motor(drv.unit_id, motor)
            res = function(self.gw, drv, *args, **kwargs)
        except KeyboardInterrupt:
            self.gw.reset()
            raise
        finally:
            self.gw.drive_motor(drv.unit_id, False)
            self.gw.drive_deselect()
        return res


    def rpm(self, drive: str) -> float:
        """Get the RPM of the drive when there's a disk in there"""
        def measure_rpm(gw: USB.Unit, drv: util.Drive, *args, **kwargs):
            flux = gw.read_track(1)
            tpr = flux.index_list[-1] / flux.sample_freq
            return 60 / tpr
        r = self.use_drive(measure_rpm, drive, True)
        return r


    def probe(self, drive: str) -> list:
        """Look at the drive and try to figure out what disk is in there"""
        print(self.drives[drive])









def main():
    logging.basicConfig(level=logging.DEBUG)
    fdr = FloppyReader(sys.path[0] + "/FloppyDiskReader.conf")
    for d in fdr.drives:
        logging.info(f"RPM for {d}: {fdr.rpm(d)}")
        logging.info(f"Probe {d}: {fdr.probe(d)}")


if __name__ == "__main__":
    main()

