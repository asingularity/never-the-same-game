Measure how player is doing at the game over time. Adjust difficulty accordingly.

Change all of these in the code for the game over time:  
- Type 1 change: some threshold or numerical difficulty, keeping all else constant, like changing lifespan, health hits, enemy speed
- Type 2 change: some qualitative change, but keeping overal game mechanics constant, like adding a wall to block movement (in 2D) or adding a new enemy type, new weapon type, etc.
- Type 3 change: qualitative change that affects the game mechanic, while keeping overall game concept or game type in place. Like, adding a new way to score in a 2D maze game by introducing a competing AI-player where there wasn't one before; or modifying a side-scroller such that the player flies a hovering vehicle instead of walking on the ground. 
- Type 4 change: Keeping only some superficial aspect if any, but changing from a side scroller to i.e. a 3D shooter, or from a block stacking puzzle game to a side scroller or 2D maze. The type of change i.e. is like a space shooter spaceship starting to grow a tail and become a snake.

These examples are only purely illustrative, there should be much greater variation than just the above. 

Any changes, of any of the types, should be smooth and continuous. I.e. even for a Type 4 change, it should take a minute or so at least to make the full change; it should be introduced by parts, intentionally. 

At any given moment or round, only one of these should change. For a type 4 change, each of these would change (but in sequence over a few rounds or game moments, not simultaneously):
- game visual look / game board
- game mechanic / dynamic
- player visual look / feel
- player's mapping from controls to player mechanic / dynamic
- scoring mechanism and rules

Approximate time intervals on which these changes should occur:
Type 1: every 10s of seconds
Type 2: every 30s to a minute
Type 3: every 2-3 minutes
Type 4: every 5 minutes

Have a box to the right of the gameplay area which actually summarizes the current rules in a few words.

Side bar should reflect changes when "rule changes" occur. 

The most important are the bigger game changes happening smoothly; add in smaller ones as those changes are being in made. There should alwyas be a type 4 change in progress, and a type 3, etc.\
