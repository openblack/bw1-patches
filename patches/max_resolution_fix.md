# Max Resolution Fix

Black & White will crash on resolution's with a width or height higher then 2048 pixels.

This is due to a failure in creating a Direct3D device, in the DLL `d3dim700.dll` in the method
`DIRECT3DDEVICEI::Init` there is a check for a width or height of over `2048` if this is the case
the error code: `0x88760082` is returned resulting in no device being created.

Removing this check fixes this allowing you to run Black & White in 1440p and even 4k resolutions.

This is done with a simple proxy DLL on `d3dim.dll` and `d3dim700.dll` which then removes the check.

# Credits

* https://github.com/UCyborg/LegacyD3DResolutionHack - for the original findings of the width/height check.