# Fixing Detail Level

When Black & White 1 was shipped it came with several different detail modes with a custom
detail mode intended for advanced users. The idea is that you can enable additional features with
the custom setting option. This however is not true and the custom setting level actually
results in many features being turned off and most custom options being ignored. The simplest
way to get the best apperance out of the game is to use the maximum detail level.

The detail levels are as follows:

* 0: Lowest Detail
* 1: Low Detail
* 2: Medium Detail
* 3: High Detail
* 4: Maximum Detail
* 5: Custom Detail

By default the configuration reader has a few hindrances that we will need to patch out.

## Procedure

The following lines of assembly are from the procedure from `.text:00642D80` to `.text:006433FE`.
The procedure is compiled from `PCMain.cpp` and is responsible for loading the registry configuration.

The first issue is if no detail index is set the game will try to automatically adjust to the best
detail level it deems. The assmebly isn't easily translated but the C style syntax of how it works is so:

```c
cpuSpeed = GetCPUSpeed();
if ( cpuSpeed <= 640 )
  if ( cpuSpeed < 420 )
    detailIdx = (cpuSpeed >= 360) + 1;
else
  detailIdx = 4;
```

GetCPUSpeed is a procedure that depends on counting the number of ticks between a `Sleep(100)` call.
It simply doesn't work very well and also uses a signed integer, it overflows often and provides a completely
inaccurate representation of the CPU speed.

The next issue we have to fix is a range check on the user provided detail level, if the user provides the
dreaded `Custom` detail level, we don't want to accept it. The game already does a range check on the user
provided detail level before dropping into the auto adjuster.

```c
if ( RegistryRetrieveULong("Software\\Lionhead Studios Ltd\\Black & White\\BWSetup", "detailidx", &regDetailIdx) || regDetailIdx >= 7 )
```

Detail levels higher than 4 are custom types and don't work properly.

## Patch

To patch the auto configuration we will simply remove it by NOPing it out and let the default value be maximum.
We NOP out the following: `.text:00642FF8` to `.text:0064301E`.

We want to adjust the range check on the registry detail level reader to disallow the custom detail level, we
can do this by changing the byte at `.text:00642FF1` from `0x07` to `0x04` which will change the range check to `>= 4`

The last thing we want to do is very simple and that's change the default detail level from High to Maximum.
We do ths by changing the following byte at `.text:00642FDE` from `0x03` to `0x04`
