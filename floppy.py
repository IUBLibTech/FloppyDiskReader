#!/bin/env python3
from typing import Callable, Tuple
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
    '5.25DD': {'tracks': 40, 'heads': 2, 'rpm': 300},
    '5.25HD': {'tracks': 80, 'heads': 2, 'rpm': 360},
    '3.5DD': {'tracks': 80, 'heads': 2, 'rpm': 300},
    '3.5HD': {'tracks': 80, 'heads': 2, 'rpm': 300}
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

        self.extension_map = {}        
        for suffix in util.image_types:
            iclass = util.get_image_class('x' + suffix)
            if iclass.default_format:
                self.extension_map[iclass.default_format] = (suffix, iclass)



    def use_drive(self, function, drive: str, *args, motor: bool = True, **kwargs):
        """Select the drive, optionally turn on the motor, and then run the function
        The function will be called with these arguments:
        function(the greaseweazle, the drive, *args, **kwargs)        
        """
        if drive not in self.drives:
            raise KeyError("This drive is not configured")
        
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


    def reset(self):
        """Reset the greaseweazle"""
        self.gw.reset()


    def rpm(self, drive: str) -> float:
        """Get the RPM of the drive when there's a disk in there"""
        def measure_rpm(gw: USB.Unit, drv: util.Drive, *args):
            gw.seek(0, 0)
            flux = gw.read_track(1)
            tpr = flux.index_list[-1] / flux.sample_freq
            return 60 / tpr
        r = self.use_drive(measure_rpm, drive, motor=True)
        return r


    def get_formats_for_drive(self, drive: str) -> dict[str, codec.DiskDef]:
        """Get a list of the formats supported for that drive"""
        return {f: codec.get_diskdef(f) for f in self.config.formats.get(self.drives[drive]['type'], [])}
        

    def probe(self, drive: str, callback: Callable = None) -> dict[str, tuple[float, int]]:
        """Look at the drive and try to figure out what disk is in there
            We're going to do this by reading the first track and see if it works.
            We're not going to deal with the weird CP/M machines that had an FM
              track on 0, but MFM elsewhere.        

            Returns a dictionary of all of the found formats with tuples indicating
            their % of sectors found and their guesstimated total capacity.  
            
            For formats with an equal percentage, it's best to use the one with
            the largest total capacity, usually.
        """
        if drive not in self.drives:
            raise KeyError("This drive is not configured")
        
        if callback is None: 
            callback = lambda x: x
        
        drive_params = self.drives[drive]
        formats = self.get_formats_for_drive(drive)
        if not formats:
            raise ValueError(f"No formats defined for drive type {self.drives[drive]['type']}")
    
        def probe_track(gw: USB.Unit, drv: util.Drive, format_name: str, fmt: codec.DiskDef) -> Tuple[float, int]:
            "Returns a tuple of percentage of sectors read for this format and the total number of sectors"
            total_expected = 0
            total_missing = 0            
            for h in range(fmt.heads):
                gw.seek(0, h)
                flux = gw.read_track(2)             
                dat = fmt.decode_flux(0, h, flux)             
                if dat.nr_missing() == dat.nsec:                    
                    return (0, 0, 0, 0)
                total_expected += dat.nsec
                total_missing += dat.nr_missing()                
                            
            #return (100 * (total_expected - total_missing) / total_expected, fmt.heads * fmt.cyls * dat.nsec)
            return (100 * (total_expected - total_missing) / total_expected, fmt.heads, fmt.cyls, dat.nsec)

        res = {}
        current = 0
        total = len(formats)
        for format_name in formats:                        
            fmt: codec.DiskDef = formats[format_name] #codec.get_diskdef(format_name)   
            if callback({'message': f"Probing {format_name}",
                         'progress': current / total}):                
                return {}
            current += 1
            if fmt.cyls > drive_params['tracks'] or fmt.heads > drive_params['heads']:
                logging.warning(f"Skipping format {format_name} because it is incompatible with the drive")
                continue
            pct, h, c, s = self.use_drive(probe_track, drive, format_name, fmt)
            if pct > 0:
                res[format_name] = (pct, h, c, s)
        return res
    

    def get_extension_for_format(self, format: str) -> str:
        """Get a list of acceptable file extensions for the format in question"""        
        return self.extension_map.get(format, ('.img', None))[0]


    def read_image(self, drive: str, format: str, filename: str,
                   track_min: int=0, track_max=81, head_min=0,
                   head_max=2, max_retries=3, callback: Callable=None):
        image_class: image.Image = util.get_image_class(filename)
        fmt: codec.DiskDef = codec.get_diskdef(format)              
        img = image_class.to_file(filename, fmt, False, {})
        img.write_on_ctrl_c = True
        track_min = max(0, min(track_min, fmt.cyls))
        track_max = min(fmt.cyls, track_max)
        head_min = max(0, min(head_min, fmt.heads))
        head_max = min(fmt.heads, head_max)
        step = 2 if self.drives[drive]['tracks'] > fmt.cyls else 1
        if callback is None:
            # create a do-nothing callback
            callback = lambda x: x

        total = (track_max - track_min) * (head_max - head_min)
        

        def reader(gw: USB.Unit, drv: util.Drive):            
            current = 0
            for cyl in range(track_min, track_max):
                pcyl = cyl * step
                for head in range(head_min, head_max): 
                    gw.seek(pcyl, head)
                    retries = max_retries
                    current += 1
                    while retries:
                        flux = gw.read_track(max(2, fmt.default_revs))  
                        dat = fmt.decode_flux(cyl, head, flux) 
                        if dat.nr_missing() == 0:
                            if callback({'success': True,
                                         'message': 'successfully read track',
                                         'head': head,
                                         'logical_cylinder': cyl,
                                         'physical_cylinder': pcyl,
                                         'flux': flux.summary_string(),
                                         'dat': dat.summary_string(),
                                         'progress': current / total}):
                                return False
                            break
                        retries -= 1                      
                        if callback({'success': False,
                                     'message': 'failed read track, retrying',
                                     'head': head,
                                     'logical_cylinder': cyl,
                                     'physical_cylinder': pcyl,
                                     'flux': flux.summary_string(),
                                     'dat': dat.summary_string(),
                                     'progress': current / total}):
                            return False
                    else:                        
                        bad = ''.join(['.' if dat.has_sec(i) else 'B' for i in range(dat.nsec)])
                        if callback({'success': False,
                                     'message': f'failed read track, data may not be usable: [{bad}]',
                                     'head': head,
                                     'logical_cylinder': cyl,
                                     'physical_cylinder': pcyl,
                                     'flux': flux.summary_string(),
                                     'dat': dat.summary_string(),
                                     'progress': current / total}):
                            return False
                        
                    img.emit_track(cyl, head, dat)

            with open(filename, "wb") as f:
                f.write(img.get_image())

            return True
                
        return self.use_drive(reader, drive)
  

def main():
    logging.basicConfig(level=logging.DEBUG)
    fdr = FloppyReader(sys.path[0] + "/FloppyDiskReader.conf")
    for d in ():
        #logging.info(f"RPM for {d}: {fdr.rpm(d)}")
        logging.info(f"Probe {d}: {fdr.probe(d)}")
    #for f in fdr.config.formats['5.25HD']:
    #    print(f, fdr.get_extension_for_format(f))
    fdr.read_image("0", "commodore.1541", "/tmp/test.d64", callback=lambda x: print(yaml.safe_dump(x)))

if __name__ == "__main__":
    main()

