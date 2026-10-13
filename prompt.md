### Overview
Write a program to play "The Towers of Hanoi" as a batch operation. The program is given an arbitrary starting position of pieces on the 3 towers plus a target tower, and produces a list of moves that results in all the pieces being correctly stacked on the target tower. Towers are labelled A, B  & C. Pieces are labelled as numbers and there can be any number of pieces up to 500000. 1 is the largest piece and for any game, the pieces will be numbered as a monotonically increasing set from 1..n
### Input
The program is passed 4 parameters. 
Parameter 1: the target tower
Parameter 2: the pieces on tower A in order from the bottom.
Parameter 3: the pieces on tower B in order from the bottom.
Parameter 4: the pieces on tower C in order from the bottom.
For all towers, a contiguous sequence of pieces can be represented as n-m, single pieces are just the number, entries are separated by spaces.
A piece can only be on 1 tower and each tower will be a legal Towers of Hanoi tower.
##### example
```
C
1 3 5-9 11

2,4,10
```
tower A has 1 3 5 6 7 8 9 11
tower B is empty
tower C has 2 4 10
game is complete when all pieces are on C
### Output
The program will write an output file with 1 line per move, each line will be 2 characters identifying the source and destination towers for the piece to be moved.
### Other requirements
Use entirely your own resources to achieve this. Do not search the web or other external sources for information on The Towers of Hanoi or code to solve it. Ask if you require any further information.
Code readability is important. Make sure that the program can handle arbitrarily large numbers of pieces without consuming excessive memory. This is a command line program (no GUI).
