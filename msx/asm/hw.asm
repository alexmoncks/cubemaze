; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Alex Moncks
; ============================================================================
; hw.asm - the V9968 and geo3d set-up, the VRAM contents, the keys, the
; messages when the hardware is missing
; ============================================================================

; ----------------------------------------------------------------------------
; VDP set-up: SCREEN 7 on the V9968 in V9968 mode (256 KB, LRMM), high-speed
; commands, EPAL, sprites off; the LRMM window over the whole VRAM; the
; palette; pages 0-1 cleared; the background, the glyph masks and the ball
; images in VRAM.
vdp_init:
        call wait_ce
        xor a
        out (VDP_PORT4), a              ; bit 7 = 0: unlock R#20 / R#21
        xor a
        ld b, 21
        call vdp_wreg                   ; R#21 = 0: V9968 mode
        ld a, 0x91                      ; S16, EPAL (15-bit palette), HS
        ld b, 20
        call vdp_wreg
        ld hl, init_regs
vi_1:   ld a, (hl)
        cp 0xFF
        jr z, vi_2
        ld b, a
        inc hl
        ld a, (hl)
        inc hl
        call vdp_wreg
        jr vi_1
vi_2:   ; the palette (16 entries, 3 bytes each)
        xor a
        ld b, 16
        call vdp_wreg
        ld hl, T_PAL0
        ld bc, 48 * 256 + VDP_PAL
        otir
        ld a, (T_FCOL)
        ld (pal_act), a
        ; pages 0 and 1: black
        ld hl, 0
        ld de, 0
        ld bc, 512
        ld ix, 512
        xor a
        call hmmv
        call wait_ce
        ; the background: the two checkerboard lines, then doubled by HMMM
        ld a, TBANK4
        call setbank
        ld hl, (BG_Y * 256) & 0xFFFF
        ld a, (BG_Y * 256) >> 14
        call vram_at
        ld hl, T_CHECK
        ld de, 512
        ld c, VDP_DATA
        call otir_n
        ld hl, 2                        ; lines done
vi_bg:  ld (bgdone), hl
        ex de, hl                       ; DE = done
        ld hl, 212
        or a
        sbc hl, de                      ; HL = lines left
        push hl
        or a
        sbc hl, de
        pop hl
        jr c, vi_b1                     ; left < done: copy what is left
        ld h, d
        ld l, e                         ; else copy done lines
vi_b1:  push hl
        pop ix                          ; NY
        ld hl, 0
        ld (cp_sx), hl
        ld hl, BG_Y
        ld (cp_sy), hl
        ld hl, (bgdone)
        ld de, BG_Y
        add hl, de
        ex de, hl                       ; DY = BG_Y + done
        ld hl, 0
        ld bc, 512
        ld a, 0xD0
        call copy_cmd
        ld hl, (bgdone)
        add hl, hl
        push hl
        ld de, 212
        or a
        sbc hl, de
        pop hl
        jr c, vi_bg
        call wait_ce
        ; the stars: (address low, middle | 40h, R#14, value), FFh FFh FFh: end
        ld hl, T_STARS
vi_s1:  ld a, (hl)
        inc hl
        ld e, a
        ld a, (hl)
        inc hl
        ld d, a
        ld a, (hl)
        inc hl
        cp 0xFF
        jr z, vi_f
        ld b, 14
        call vdp_wreg
        ld a, e
        out (VDP_CTRL), a
        ld a, d
        out (VDP_CTRL), a
        ld a, (hl)
        inc hl
        out (VDP_DATA), a
        jr vi_s1
vi_f:   ; the glyph masks (bank 3): FONT_Y, 42 lines
        ld a, TBANK3
        call setbank
        ld hl, (FONT_Y * 256) & 0xFFFF
        ld a, (FONT_Y * 256) >> 14
        call vram_at
        ld hl, T_FONT
        ld de, 42 * 256
        ld c, VDP_DATA
        call otir_n
        ; the ball images (bank 4): (low, middle | 40h, R#14, count) + bytes
        ld a, TBANK4
        call setbank
        ld hl, T_BALLIMG
vi_b2:  ld e, (hl)
        inc hl
        ld d, (hl)
        inc hl
        ld a, (hl)
        inc hl
        cp 0xFF
        jr z, vi_end
        ld b, 14
        call vdp_wreg
        ld a, e
        out (VDP_CTRL), a
        ld a, d
        out (VDP_CTRL), a
        ld b, (hl)
        inc hl
        ld c, VDP_DATA
        otir
        jr vi_b2
vi_end: xor a
        ld b, 14
        call vdp_wreg
        ret

bgdone:     equ RAM + 0x478

; VRAM write address: A = address bits 16-14 (R#14), HL = the address
vram_at:
        ld b, 14
        call vdp_wreg
        ld a, l
        out (VDP_CTRL), a
        ld a, h
        and 0x3F
        or 0x40
        out (VDP_CTRL), a
        ret

; HL = source, DE = byte count, C = port
otir_n: ld a, d
        or a
        jr z, on_2
on_1:   ld b, 0
        otir
        dec d
        jr nz, on_1
on_2:   ld a, e
        or a
        ret z
        ld b, a
        otir
        ret

init_regs:
        db 1, 0x00                      ; display off, no interrupts
        db 0, 0x0A                      ; GRAPHIC6 (SCREEN 7)
        db 2, 0x1F                      ; page 0
        db 7, 0x00                      ; black border
        db 8, 0x0A                      ; sprites off
        db 9, 0x80                      ; 212 lines, 60 Hz
        db 15, 0x00
        db 23, 0x00
        db 25, 0x00
        db 26, 0x00
        db 27, 0x00
        db 51, 0x00                     ; LRMM window: x 0 .. 511,
        db 52, 0x00
        db 53, 0x00                     ; y 0 .. 2047
        db 54, 0x00
        db 55, 0xFF
        db 56, 0x01
        db 57, 0xFF
        db 58, 0x07
        db 0xFF

; geo3d: extended mode, the camera, no shading copies
geo_init:
        ld a, 0x6F
        out (GEO_IDX), a
        ld a, 1
        out (GEO_DAT), a
        ld a, 0x18
        out (GEO_IDX), a
        ld hl, geo_cam
        ld bc, 12 * 256 + GEO_DAT
        otir
        ld a, 0x64
        out (GEO_IDX), a
        xor a
        out (GEO_DAT), a
        ret

geo_cam:
        dw G_FOCAL, G_CX, G_CY, G_ZNEAR, G_W, G_H

; ----------------------------------------------------------------------------
; the keys: A = bits 0 up, 1 down, 2 left, 3 right, 4 SPACE / trigger A,
; 5 ESC / trigger B (joystick port 1 too)
read_keys:
        ld a, 8
        call key_row
        ld c, 0
        bit 5, a
        jr z, rk_1
        set 0, c
rk_1:   bit 6, a
        jr z, rk_2
        set 1, c
rk_2:   bit 4, a
        jr z, rk_3
        set 2, c
rk_3:   bit 7, a
        jr z, rk_4
        set 3, c
rk_4:   bit 0, a
        jr z, rk_5
        set 4, c
rk_5:   ld a, 7
        call key_row
        bit 2, a
        jr z, rk_6
        set 5, c
rk_6:   ; joystick 1: R#15 bit 6 = 0, then R#14 (0 = pressed)
        ld a, 15
        out (PSG_A), a
        in a, (PSG_R)
        and 0xBF
        out (PSG_D), a
        ld a, 14
        out (PSG_A), a
        in a, (PSG_R)
        cpl
        and 0x3F
        or c
        ret

key_row:                                ; A = row; returns its keys, 1 = down
        ld b, a
        in a, (PPI_C)
        and 0xF0
        or b
        out (PPI_C), a
        in a, (PPI_B)
        cpl
        ret

; ----------------------------------------------------------------------------
; geo_probe: geo3d at PORT_BASE (as sphere7.asm), then its ID: 20h = v2.0.
; Z: found. (B = 1 when an older geo3d answered.)
geo_probe:
        if PORT_BASE == 0x98
        ld a, (MSXVER)
        or a
        jr z, gp_no                     ; an MSX1: a TMS9918 at 98h
        endif
        ld a, 1
        ld b, 15
        call vdp_wreg
        in a, (VDP_CTRL)                ; S#1
        ld e, a
        xor a
        ld b, 15
        call vdp_wreg
        ld a, e
        rrca
        and 0x1F
        cp 2
        jr c, gp_no                     ; V9938 (0), V9948 (1)
        cp 4
        jr nc, gp_no                    ; not a V99x8
        ld a, 2
        ld b, 15
        call vdp_wreg
        in a, (GEO_IDX)
        ld e, 0xFF
        cp 0xFF
        jr z, gp_1
        and 0x0C
        cp 0x0C
        jr z, gp_1                      ; S#2 of a VDP repeated at P+4..P+7
        in a, (VDP_PORT4)
        ld e, a
gp_1:   xor a
        ld b, 15
        call vdp_wreg
        ld a, e
        and 0x78
        jr nz, gp_no
        ld a, 0x40
        out (GEO_IDX), a
        in a, (GEO_DAT)                 ; 40h
        ld d, a
        in a, (GEO_DAT)
        in a, (GEO_DAT)
        in a, (GEO_DAT)
        in a, (GEO_DAT)
        in a, (GEO_DAT)                 ; 45h LOP
        and 0xF0
        jr nz, gp_no
        in a, (GEO_DAT)
        in a, (GEO_DAT)                 ; 47h
        and 0xF8
        jr nz, gp_no
        ld b, 8
gp_2:   in a, (GEO_DAT)
        djnz gp_2
        in a, (GEO_DAT)                 ; 40h again
        cp d
        jr nz, gp_no
        ld a, 0x49
        out (GEO_IDX), a
        in a, (GEO_DAT)
        cp 0x20
        ret z
        ld b, 1
        or 0xFF
        ret
gp_no:  ld b, 0
        or 0xFF
        ret

; ----------------------------------------------------------------------------
; No geo3d (or not v2.0), or it (or the command engine) stopped answering: a
; message on the MSX's own text screen (BIOS), and stay there.
hw_fail:
        di
        ld sp, STACK_TOP
        xor a
        ld b, 46
        call vdp_wreg                   ; STOP the command engine
        ld hl, msg_fail
        jr ng_text
nogeo:
        ld hl, msg_nogeo
        ld a, b
        or a
        jr z, ng_text
        ld hl, msg_oldgeo
ng_text:
        push hl
        call INITXT
        di
        pop hl
ng_1:   ld a, (hl)
        or a
        jr z, ng_stay
        push hl
        call CHPUT
        di
        pop hl
        inc hl
        jr ng_1
ng_stay:
        jr ng_stay

msg_nogeo:
        db "CUBE MAZE 3D: geo3d not found.", 13, 10
        if PORT_BASE == 0x88
        db "It needs the V9968 cartridge with the", 13, 10
        db "geo3d v2.0 build, DIP switch at 88h.", 13, 10, 0
        else
        db "It needs a V9968 at 98h with geo3d", 13, 10
        db "v2.0 (openMSX: -ext geo3d).", 13, 10, 0
        endif
msg_oldgeo:
        db "CUBE MAZE 3D needs geo3d v2.0", 13, 10
        db "(this geo3d is an older version).", 13, 10, 0
msg_fail:
        db "CUBE MAZE 3D: geo3d or the V9968", 13, 10
        db "command engine stopped answering.", 13, 10, 0
