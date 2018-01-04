# Skip Tutorial

Skipping the tutorial can be a desired feature for veterens of the game. The game by default offers this
functionality if you have more then 1 profile or if you already have a creature on the current profile.

## Procedure

When a new game is started the method `GGame::OnNewGame(void *this)` calls the following static method:

```cpp
void GGame::DoYesNoSkipTutorialRequestersIfNecessary()
{
    if ( PlayerProfile::GetNumberOfProfiles() > 1 || g_Game->CurrentProfileHasACreature() )
    {
        PauseGame(1);
        g_SkipBox->Show();
    }
}
```

Depending on the action taken by the user in the skip box dialog, GGame constants are changed to skip the
tutorial. Knowing this we can simple remove the if condition required to show the skip dialog so the method
would read:

```cpp
void GGame::DoYesNoSkipTutorialRequestersIfNecessary()
{
    PauseGame(1);
    g_SkipBox->Show();
}
```

## Patch

The method `GGame::DoYesNoSkipTutorialRequestersIfNecessary()` is a function at `.text:0054CBD0` to `.text:0054CC22`.
The condition can simply be patched out by simply replacing `.text:0054CBF4` to `.text:0054CC0B` with `0x90` (NOP).

After these changes the game will prompt you to skip the tutorial on new game regardless of if you have a profile
already.