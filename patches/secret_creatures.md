# Secret Creatures

Black & White has secret creatures for different disc editions of the game. By default these include the:

* Gorilla
* Horse
* Leopard
* Mandrill

These could be unlocked previously by running creature unlockers released by Lionhead, however on recent operating systems these no longer work.

We can patch the method directly in the game to unlock all secret creatures by default, including a **hidden Rhino creature** never unlocked before.

## Procedure

When a creature unlocker is run there are two registry values written to in BWSetup: `TimerValue` and `TimerCheckSum`. (_presumably for obfuscation_)
These appear to be tied to your Windows product key as well, which it can't grab on newer Windows versions so it just doesn't work.

Fortunately we don't have to mess with this, as there's a nice method in the game we can change called `SecretCreature::IsCreaturePresent`. It simply returns a boolean value if the given integer enum is unlocked:

```c
BOOL __cdecl SecretCreature::IsCreaturePresent(int a1)
{
  return (qword_D99040 & (1i64 << dword_957248[a1])) != 0;
}
```

So let's just change it to look like this:

```c
BOOL __cdecl SecretCreature::IsCreaturePresent(int a1)
{
  return true;
}
```

Everything unlocked.

## Patch

`SecretCreature::IsCreaturePresent` exists at `.text:00711D90`.

We can replace the entire function with:

```asm
mov eax, 1
retn
```

Which in machine code looks like this:

* `B8 01 00 00 00`
* `C3`

