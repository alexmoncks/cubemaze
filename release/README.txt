CUBE MAZE 3D - for MSX2 + V9968 + geo3d v2.0
=============================================

A port of "Cube Maze 3D" by harukaappscreate (JavaScript, Playload engine),
made with the original author's permission. Roll a ball through a maze that
covers the six faces of a cube; crossing an edge rolls the cube.

Files
  CUBEMAZE_98.ROM   V9968 at ports 98h, geo3d at 9Dh/9Fh (emulators)
  CUBEMAZE_88.ROM   V9968 cartridge at ports 88h (real hardware, the DIP
                    switch at 88h), geo3d at 8Dh/8Fh
Both are 128 KB MegaROMs, ASCII16 mapper, built from geo3d/cubemaze/msx
(build.sh). They need an MSX2 or later and geo3d v2.0 (an older geo3d is
reported on the text screen). MSX-MUSIC (internal or FM-PAC) plays the
music when present, the PSG otherwise. In the openMSX fork with geo3d
(github.com/alexmoncks/openMSX, branch geo3d):
  openmsx -machine C-BIOS_V9968_JP -ext geo3d -cart CUBEMAZE_98.ROM -romtype ASCII16

Controls
  cursor keys or joystick 1     roll the ball; on the title, pick the size;
                                on the code screen, edit the code
  SPACE or trigger A            start, skip the preview, next stage, OK
  ESC or trigger B              in play: retry the maze
                                on the title: the stage code screen
                                elsewhere: back

Stage codes (the MSX does not save the progress)
  NRPT   unlocks up to 4x4
  B4SX   unlocks up to 5x5
  MHXV   unlocks up to 6x6
The clear screen shows the code of the size just unlocked.

Frame rate
  At most 30 pictures a second; the game runs 60 ticks a second as the
  original (a slower picture advances the game by more ticks).
  Estimated on the RTL (geo3d driving HRA!'s command engine): about 17-18
  pictures a second in play, about 15 on the title, about 12 on the clear
  screen. Real hardware may be a little slower; the game's speed is not.

----------------------------------------------------------------------------
Portugues

  CUBEMAZE_98.ROM   V9968 nas portas 98h, geo3d em 9Dh/9Fh (emuladores)
  CUBEMAZE_88.ROM   cartucho V9968 nas portas 88h (hardware real, chave DIP
                    em 88h), geo3d em 8Dh/8Fh
Port do "Cube Maze 3D" de harukaappscreate, feito com a permissao do autor
original. Precisa de MSX2 ou superior e do geo3d v2.0. Com MSX-MUSIC
(interno ou FM-PAC) a musica sai pelo FM; sem ele, pelo PSG. No openMSX
(fork com o geo3d), use a linha de comando mostrada acima.

Controles
  setas ou joystick 1           rolam a bola; no titulo escolhem o tamanho;
                                na tela de codigo editam o codigo
  ESPACO ou botao A             comeca, pula a previa, proxima fase, OK
  ESC ou botao B                no jogo: recomeca o labirinto
                                no titulo: tela de codigo de fase
                                nas outras telas: volta

Codigos de fase (o MSX nao grava o progresso)
  NRPT   libera ate 4x4
  B4SX   libera ate 5x5
  MHXV   libera ate 6x6
A tela de fase concluida mostra o codigo do tamanho liberado.

Taxa de quadros
  No maximo 30 imagens por segundo; o jogo roda a 60 ticks por segundo como
  o original (uma imagem mais lenta avanca o jogo em mais ticks).
  Estimativa no RTL (geo3d com o motor de comandos do HRA!): cerca de 17 a
  18 imagens por segundo no jogo, cerca de 15 no titulo, cerca de 12 na tela
  de fase concluida. O hardware real pode ser um pouco mais lento; a
  velocidade do jogo nao muda.
