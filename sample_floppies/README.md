# Sample Floppy Disk Images
These are images which can be written to real floppies for testing.  

Each floppy is empty with the exception of some small sample data, such as
a basic program or text file.

The actual process will vary based on your hardware configuration, but
this should get you started.

The WRITE-ENABLE jumper must be present on the greaseweazle.

NOTE:  Writing 5.25" DD disks in an HD drive is not advised because of the
magnetic characteristics of the media.

Activate the Python Virtual Environment so the greaseweazle software is
in the path:

```
source .venv/bin/activate
```

Erase the disk.  If you are using a 40-track drive you will need to specify
which tracks to erase:

```
gw erase --drive A --tracks c=0-39
```

You may need to reset the greaseweazle if it's lost the index marker:

```
gw reset
```


Write the disk, specifying the format:
```
gw write --drive A --format commodore.1541 commodore_1541.d64
```


Generally the filenames are the greasweazle format name, substituting the '_'
with a '.'.

However, `ibm_1440_mac.img` is an `ibm.1440` formatted disk (flux-wise) but has
a Macintosh HFS filesystem on it, which is a normal configuration.

