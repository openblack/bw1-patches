# Addons / Extra Features

Black & White has [addons / extra features](http://www.bwfiles.com/files/category.php?id=23)
that can be enabled by the user by installing them. The official addons are:

* Football Addon
* Villager Banter
* MP3 Addon

Addons don't appear to work at all by default on Windows Vista and upwards.

## Procedure

The following lines of assembly are from the procedure from `.text:00525A40` to `.text:00525B7D`.
The procedure is compiled from `ExtraFeatures.cpp` and is used to check if the given addon name
is installed. It checks a preset of strings:

* `BWMP3Player`
* `CreatureDanceLineIn`
* `CreatureMusicMood`
* `football`

Straight away in the procedure we can see exaclty where the procedure is getting caught each time.

```
if ( RegistryRetrieveString("Software\Microsoft\Windows\CurrentVersion", "ProductId", &productID, &v10) == 2 )
{		
	LHRegistrySetCurrentKey(v2);
	return 0;
}
```

The key `Software\Microsoft\Windows\CurrentVersion\ProductId` does not exist on newer versions of
Windows. This registry key was moved to `Software\Microsoft\Windows NT\CurrentVersion\ProductId`

## Patch

We simply remove the check for the existence of the product id by changing the byte at `.text:00525AD2`
from `75` to `EB`.