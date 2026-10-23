; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Alex Moncks
; ============================================================================
; render.asm - one picture (zmodel.py Machine.draw), the textures of a maze
; (Machine.bake)
; ============================================================================

draw_frame:
        ; 1. the background (checkerboard + stars) onto the hidden page
        ld hl, 0
        ld (cp_sx), hl
        ld hl, BG_Y
        ld (cp_sy), hl
        ld hl, 0
        ld a, (pg)
        ld d, a
        ld e, 0
        ld bc, 512
        ld ix, 212
        ld a, 0xD0
        call copy_cmd
        ; 2. the matrix, TX TY TZ, YPAGE
        call make_matrix
        xor a
        out (GEO_IDX), a
        ld hl, mat
        ld bc, 18 * 256 + GEO_DAT
        otir
        xor a
        out (GEO_DAT), a
        out (GEO_DAT), a
        out (GEO_DAT), a
        out (GEO_DAT), a
        ld a, TZ & 0xFF
        out (GEO_DAT), a
        ld a, TZ >> 8
        out (GEO_DAT), a
        ld a, 0x46
        out (GEO_IDX), a
        xor a
        out (GEO_DAT), a
        ld a, (pg)
        out (GEO_DAT), a
        ; 3. the faces in view, 4. their blocks in geo3d's RAMs
        call find_vis
        call do_slots
        ; 5. the ball and its shadow, projected by geo3d
        call ball_points
        ld hl, bm
        call project
        ld (b_px), hl
        ld (b_py), de
        ld (b_pz), bc
        ld hl, bsh
        call project
        ld (b_qx), hl
        ld (b_qy), de
        ; 6. the floors: LOP = OR
        ld a, 0x45
        out (GEO_IDX), a
        ld a, 2
        out (GEO_DAT), a
        ld a, 1
        ld (df_first), a
        ld ix, vis
        ld iy, vslot
        ld a, (vis_n)
        or a
        jp z, df_layers
        ld b, a
df_f1:  push bc
        call ctx_load
        ld hl, (cur_vb)
        ld a, 0x54
        ld b, 0x55
        call g10                        ; VFIRST
        call block_nv
        ld a, 0x42
        ld b, 0x6A
        call g10                        ; NVERT
        ; TEXX, TEXY: the face's slot (active or not)
        ld a, 0x60
        out (GEO_IDX), a
        ld a, (cur_face)
        add a, a
        ld hl, cur_act
        add a, (hl)                     ; s = 2 f + active
        ld b, a
        and 3
        rrca
        rrca                            ; (s & 3) * 64 -> * 128: low byte 0 / 128
        ld c, a
        add a, a                        ; (s & 3) * 128 low byte
        out (GEO_DAT), a
        ld a, b
        and 3
        srl a                           ; high byte of (s & 3) * 128
        out (GEO_DAT), a
        ld a, b
        rrca
        rrca
        and 3                           ; s >> 2
        ld h, 0
        ld l, a
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl                      ; * 64
        ld de, TEX_Y
        add hl, de
        ld a, l
        out (GEO_DAT), a
        ld a, h
        out (GEO_DAT), a
        ld hl, (cur_fb)
        ld a, 0x56
        ld b, 0x57
        call g10                        ; FFIRST
        ld a, (nn)
        ld l, a
        ld h, 0
        ld a, 0x59
        ld b, 0x6D
        call g10                        ; NFACE
        ld a, 0x48
        out (GEO_IDX), a
        ld a, 0x07
        out (GEO_DAT), a                ; RUN
        ; the occluders' search, while geo3d draws this floor: its start
        ; with the first floor, then this floor's face
        push ix
        push iy
        ld a, (df_first)
        or a
        jr z, df_o
        xor a
        ld (df_first), a
        call occ_search
df_o:   ld a, (ix + 0)
        call occ_one
        pop iy
        pop ix
df_w:   call wait_geo
        inc ix
        inc iy
        pop bc
        dec b
        jp nz, df_f1
df_layers:
        ld a, (df_first)
        or a
        call nz, occ_search             ; (no face in view)
        ; 7. the layers above: LOP = IMP, NVERT = 0
        ld a, 0x45
        out (GEO_IDX), a
        xor a
        out (GEO_DAT), a
        ld hl, 0
        ld a, 0x42
        ld b, 0x6A
        call g10
        ld ix, vis
        ld iy, vslot
        ld a, (vis_n)
        or a
        jr z, df_ball
        ld b, a
df_f2:  push bc
        call ctx_load
        ; goal1 (1), mid (nr), goal2 (1), top (nr), from local face nn
        ld a, (nn)
        ld l, a
        ld h, 0
        ld a, (cur_goal)
        or a
        jr z, df_l1
        ld b, 1
        call layer_run                  ; goal1
df_l1:  ld a, (cur_nr)
        ld b, a
        call layer_run                  ; mid
        ld a, (cur_goal)
        or a
        jr z, df_l2
        ld b, 1
        call layer_run                  ; goal2
df_l2:  ld a, (cur_nr)
        ld b, a
        call layer_run                  ; top
        inc ix
        inc iy
        pop bc
        djnz df_f2
df_ball:
        ; 8. the ball, the walls in front of it
        call wait_geo
        call draw_ball
        ; 9. the HUD
        call wait_geo
        jp hud

; a RUN of B faces from local face HL (B = 0: none); HL += B
layer_run:
        ld a, b
        or a
        ret z
        push hl
        push bc
        ld de, (cur_fb)
        add hl, de
        ld a, 0x56
        ld b, 0x57
        call g10
        pop bc
        push bc
        ld l, b
        ld h, 0
        ld a, 0x59
        ld b, 0x6D
        call g10
        call geo_run
        pop bc
        pop hl
        ld a, b
        jp add_hl_a

; RUN (faces, textures) and wait for its end
geo_run:
        ld a, 0x48
        out (GEO_IDX), a
        ld a, 0x07
        out (GEO_DAT), a
        jp wait_geo

; ----------------------------------------------------------------------------
; HL -> a point (3 words): geo3d projects it. HL = SX, DE = SY, BC = Z.
project:
        ld a, 0x24
        out (GEO_IDX), a
        ld bc, 6 * 256 + GEO_DAT
        otir
pj_1:   in a, (GEO_IDX)                 ; status: bit 3 = the core busy
        and 8
        jr nz, pj_1
        ld hl, tmp
        ld bc, 7 * 256 + GEO_DAT
        inir
        ld hl, (tmp)
        ld de, (tmp + 2)
        ld bc, (tmp + 4)
        ret

; ----------------------------------------------------------------------------
; the matrix of the frame's camera -> mat
make_matrix:
        ld a, (cam_kind)
        or a
        jr nz, mm_1
        ; spin: TITLE[t]
        ld a, TBANK1
        call setbank
        ld hl, (cam_t)
        call x18
        ld de, T_TITLE
        add hl, de
        ld de, mat
        ld bc, 18
        ldir
        ret
mm_1:   dec a
        jr nz, mm_2
        ; play: ROLLB[a][k] . P(o)
        ld a, TBANK1
        call setbank
        call roll_index                 ; HL = (a * 25 + k) * 18
        ld de, T_ROLLB
        add hl, de
        ld de, mtmp
        ld bc, 18
        ldir
        jr mm_perm
mm_2:   ; clear: CLEAR[t] (. ROLLR[a][k]) . P(o)
        ld a, TBANK2
        call setbank
        ld hl, (cam_t)
        call x18
        ld de, T_CLEAR
        add hl, de
        ld de, mtmp
        ld bc, 18
        ldir
        ld a, (cam_k)
        or a
        jr z, mm_perm
        ld a, TBANK1
        call setbank
        call roll_index
        ld de, T_ROLLR
        add hl, de
        ld de, mtmp2
        ld bc, 18
        ldir
        call mat_mul                    ; mtmp = mtmp . mtmp2
mm_perm:
        ; mat[e] = +-mtmp[src] (T_PERM9[o]: 9 x (2 * src, negate))
        ld a, (cam_o)
        ld l, a
        ld h, 0
        ld a, 18
        call mul_hl_a
        ld de, T_PERM9
        add hl, de
        ld de, mat
        ld b, 9
mp_1:   push bc
        ld a, (hl)
        inc hl
        ld c, (hl)
        inc hl
        push hl
        ld hl, mtmp
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        bit 0, c
        call nz, neg_hl
        ex de, hl
        ld (hl), e
        inc hl
        ld (hl), d
        inc hl
        ex de, hl
        pop hl
        pop bc
        djnz mp_1
        ret

; HL = HL * 18
x18:    add hl, hl
        ld d, h
        ld e, l
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, de
        ret

; HL = (cam_a * 25 + cam_k) * 18
roll_index:
        ld a, (cam_a)
        ld l, a
        ld h, 0
        ld a, 25
        call mul_hl_a
        ld a, (cam_k)
        call add_hl_a
        jr x18

; mtmp = (mtmp . mtmp2 + 8192) >> 14, element by element (Q2.14)
mat_mul:
        ld hl, mtmp
        ld de, mat                      ; (mat as the output, copied back)
        ld (tmp + 4), de
        ld c, 0                         ; i * 6
mmu_i:  ld b, 0                         ; j * 2
mmu_j:  push bc
        ld hl, 0
        ld (acc2), hl
        ld (acc2 + 2), hl
        ld e, 0                         ; k
mmu_k:  push de
        push bc
        ; a[i][k] = mtmp[c + 2k], b[k][j] = mtmp2[6k + b]
        ld a, e
        add a, a
        add a, c
        ld hl, mtmp
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        push hl
        ld a, e
        add a, a
        add a, e
        add a, a                        ; 6k
        add a, b
        ld hl, mtmp2
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        pop hl
        call mul16s                     ; acc = a * b
        ld hl, acc2
        ld de, acc
        call add32_to                   ; acc2 += acc
        pop bc
        pop de
        inc e
        ld a, e
        cp 3
        jr c, mmu_k
        ld hl, (acc2)
        ld (acc), hl
        ld hl, (acc2 + 2)
        ld (acc + 2), hl
        call acc_round
        call acc_sr14
        ex de, hl
        ld hl, (tmp + 4)
        ld (hl), e
        inc hl
        ld (hl), d
        inc hl
        ld (tmp + 4), hl
        pop bc
        inc b
        inc b
        ld a, b
        cp 6
        jr c, mmu_j
        ld a, c
        add a, 6
        ld c, a
        cp 18
        jr c, mmu_i
        ld hl, mat
        ld de, mtmp
        ld bc, 18
        ldir
        ret

; (HL) += (DE), 32 bits
add32_to:
        ld b, 4
        or a
a32_1:  ld a, (de)
        adc a, (hl)
        ld (hl), a
        inc hl
        inc de
        djnz a32_1
        ret

; ----------------------------------------------------------------------------
; the faces facing the camera (rotated normal z >= 0.19), farthest first
find_vis:
        xor a
        ld (vis_n), a
        ld c, 0                         ; face
fv_1:   ld a, c
        ld b, a
        add a, a
        add a, b
        add a, a                        ; x 6
        ld hl, T_FAXES
        call add_hl_a
        ld a, (hl)                      ; 2 * component of the normal
        inc hl
        ld b, (hl)                      ; negate
        ld hl, mat + 12
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        bit 0, b
        call nz, neg_hl                 ; v = s * M[2][i]
        ld de, VIS_T
        add hl, de                      ; v + VIS_T <= 0 ?
        ld a, h
        or l
        jr z, fv_in
        bit 7, h
        jr z, fv_next
fv_in:  ; key = -v = VIS_T - (v + VIS_T)
        ex de, hl                       ; DE = v + VIS_T
        ld hl, VIS_T
        or a
        sbc hl, de                      ; HL = -v
        ; insert (key HL, face C) keeping the order (equal keys: lower face first)
        ld a, (vis_n)
        ld b, a                         ; position from the end
fv_ins: ld a, b
        or a
        jr z, fv_put
        dec a
        push hl
        ld e, a
        ld d, 0
        ld hl, vkey
        add hl, de
        add hl, de
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a                         ; key of entry b - 1
        pop de                          ; DE = new key
        push de
        ex de, hl
        or a
        sbc hl, de                      ; new - old
        pop hl
        jr nc, fv_put                   ; new >= old: after it
        ; move entry b - 1 to b
        push hl
        ld a, b
        dec a
        ld e, a
        ld d, 0
        ld hl, vis
        add hl, de
        ld a, (hl)
        inc hl
        ld (hl), a
        ld hl, vkey
        add hl, de
        add hl, de
        ld a, (hl)
        inc hl
        inc hl
        ld (hl), a
        dec hl
        ld a, (hl)
        inc hl
        inc hl
        ld (hl), a
        pop hl
        dec b
        jr fv_ins
fv_put: ld e, b
        ld d, 0
        push hl
        ld hl, vis
        add hl, de
        ld (hl), c
        ld hl, vkey
        add hl, de
        add hl, de
        pop de
        ld (hl), e
        inc hl
        ld (hl), d
        ld hl, vis_n
        inc (hl)
fv_next:
        inc c
        ld a, c
        cp 6
        jp c, fv_1
        ret

; ----------------------------------------------------------------------------
; slots: keep the visible faces already resident, put the others in the free
; slots (lowest first); colours re-sent when a kept face's activity changed;
; the goal's two moving quads every frame
do_slots:
        ; kept[i] = slots[i].face is in vis
        ld b, 0
dk_1:   push bc
        ld a, b
        add a, a
        ld hl, slots
        call add_hl_a
        ld a, (hl)
        call in_vis
        ld a, 0
        jr nz, dk_2
        inc a
dk_2:   pop bc
        push bc
        ld hl, kept
        ld c, a
        ld a, b
        call add_hl_a
        ld (hl), c
        pop bc
        inc b
        ld a, b
        cp 3
        jr c, dk_1
        ; each visible face
        ld a, (vis_n)
        or a
        ret z
        ld b, a
        ld ix, vis
        ld iy, vslot
ds_f:   push bc
        ld a, (ix + 0)
        ld (tmp + 6), a
        ; resident and kept?
        ld hl, slots
        ld c, 0
ds_s1:  ld a, (tmp + 6)
        cp (hl)
        jr nz, ds_s2
        push hl
        ld hl, kept
        ld a, c
        call add_hl_a
        ld a, (hl)
        pop hl
        or a
        jr nz, ds_keep
ds_s2:  inc hl
        inc hl
        inc c
        ld a, c
        cp 3
        jr c, ds_s1
        ; a free slot: the first i with kept[i] = 0 (then marked used)
        ld hl, kept
        ld c, 0
ds_fr:  ld a, (hl)
        or a
        jr z, ds_new
        inc hl
        inc c
        jr ds_fr
ds_new: ld (hl), 1
        ld (iy + 0), c
        ld a, (tmp + 6)
        call face_ctx                   ; face A in slot C
        call up_verts
        call up_faces_all
        call up_uvs
        call slot_mark
        jr ds_goal
ds_keep:
        ld (iy + 0), c
        ld a, (tmp + 6)
        call face_ctx
        ; the activity at upload vs now
        ld hl, slots + 1
        ld a, (cur_slot)
        add a, a
        call add_hl_a
        ld a, (cur_act)
        cp (hl)
        jr z, ds_goal
        call up_faces_upper
        call slot_mark
ds_goal:
        ld a, (cur_goal)
        or a
        call nz, up_goal
        call ctx_save
        inc ix
        inc iy
        pop bc
        djnz ds_f
        ret

; A = face: Z when it is in vis. Changes B, C, HL.
in_vis: ld c, a
        ld a, (vis_n)
        or a
        jr z, iv_no
        ld b, a
        ld hl, vis
iv_1:   ld a, (hl)
        cp c
        ret z
        inc hl
        djnz iv_1
iv_no:  or 1
        ret

; slots[slot] = (cur_face, cur_act)
slot_mark:
        ld a, (cur_slot)
        add a, a
        ld hl, slots
        call add_hl_a
        ld a, (cur_face)
        ld (hl), a
        inc hl
        ld a, (cur_act)
        ld (hl), a
        ret

cur_slot:   equ tmp + 7

; A = face, C = slot: the face's context (axes, bases, activity, goal, runs)
face_ctx:
        ld (cur_face), a
        ld a, c
        ld (cur_slot), a
        ld a, (cur_face)
        call set_fax
        ld a, (cur_slot)
        add a, a
        ld hl, slot_vb
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld (cur_vb), de
        ld a, (cur_slot)
        add a, a
        ld hl, slot_fb
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld (cur_fb), de
        ld a, (act)
        ld hl, cur_face
        sub (hl)
        ld a, 0
        jr nz, fc_1
        inc a
fc_1:   ld (cur_act), a
        ld a, (gl_face)
        sub (hl)
        ld a, 0
        jr nz, fc_2
        inc a
fc_2:   ld (cur_goal), a
        ld a, (hl)
        ld hl, runs_n
        call add_hl_a
        ld a, (hl)
        ld (cur_nr), a
        ld a, (cur_face)
        add a, a
        ld hl, runs_p
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        ld (cur_runs), hl
        ld a, (cur_face)
        ld hl, walls_n
        call add_hl_a
        ld a, (hl)
        ld (cur_nw), a
        ld a, (cur_face)
        add a, a
        ld hl, walls_p
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        ld (cur_walls), hl
        ret

slot_vb:    dw 0, VSLOT, 2 * VSLOT
slot_fb:    dw 0, FSLOT, 2 * FSLOT

; the context of vis entry (IX - vis): saved / loaded (cur_face .. cur_nw)
ctx_ptr:
        push ix
        pop hl
        ld de, vis
        or a
        sbc hl, de
        ld a, l                         ; entry 0..2
        ld l, a
        add a, a
        add a, l
        add a, a
        add a, a                        ; x 12
        add a, l
        add a, l                        ; x 14
        ld hl, ctx
        jp add_hl_a

ctx_save:
        call ctx_ptr
        ex de, hl
        ld hl, cur_face
        ld bc, 13
        ldir
        ret

ctx_load:
        call ctx_ptr
        ld de, cur_face
        ld bc, 13
        ldir
        ret

; HL = the block's vertex count: NVF + 8 goal + 8 runs
block_nv:
        ld hl, (lvc + LV_NVF)
        ld a, (cur_goal)
        or a
        jr z, bn_1
        ld de, 8
        add hl, de
bn_1:   ld a, (cur_nr)
        ld e, a
        ld d, 0
        ex de, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, de
        ret

; ----------------------------------------------------------------------------
; vertex streams
; VADDR = HL, then the stream index
verts_at:
        ld a, 0x40
        ld b, 0x68
        call g10
        ld a, 0x50
        out (GEO_IDX), a
        ret

; the whole block of the face
up_verts:
        ld hl, (cur_vb)
        call verts_at
        ; the floor grid: (2j - lv) HG, (2i - lv) HG at KS
        ld hl, (lvc + LV_KS)
        ld (fp_n), hl
        ld a, (mlv)
        neg
        ld (uv_tv), a
        ld a, (mlv)
        inc a
        ld b, a
        call place_n
uv_i:   push bc
        ld a, (uv_tv)
        call uh_of
        ld (fp_v), hl
        ld a, (mlv)
        neg
        ld (uv_tu), a
        ld a, (mlv)
        inc a
        ld b, a
uv_j:   push bc
        ld a, (uv_tu)
        call uh_of
        ld de, (fp_v)
        call put_uv_out
        ld hl, uv_tu
        inc (hl)
        inc (hl)
        pop bc
        djnz uv_j
        ld hl, uv_tv
        inc (hl)
        inc (hl)
        pop bc
        djnz uv_i
uv_g:   ld a, (cur_goal)
        or a
        call nz, emit_goal
        ; the runs: middle layer, then top layer
        ld hl, (lvc + LV_HMID)
        call emit_runs
        ld hl, (lvc + LV_HTOP)
        jp emit_runs

; HL = height: the quads of the face's runs
emit_runs:
        ld (fp_n), hl
        ld a, (cur_nr)
        or a
        ret z
        push ix
        call er_go
        pop ix
        ret
er_go:  ld b, a
        ld ix, (cur_runs)
er_1:   push bc
        ; a = ta HG - WL, b = tb HG + WL, lo = line HG - WW, hi = line HG + WW
        ld a, (ix + 2)
        call uh_of
        ld de, (lvc + LV_WL)
        or a
        sbc hl, de
        ld (q_a), hl
        ld a, (ix + 3)
        call uh_of
        ld de, (lvc + LV_WL)
        add hl, de
        ld (q_b), hl
        ld a, (ix + 1)
        call uh_of
        push hl
        ld de, (lvc + LV_WW)
        or a
        sbc hl, de
        ld (q_lo), hl
        pop hl
        add hl, de
        ld (q_hi), hl
        ld a, (ix + 0)
        or a
        jr nz, er_v
        ld hl, (q_a)
        ld (q_u0), hl
        ld hl, (q_b)
        ld (q_u1), hl
        ld hl, (q_lo)
        ld (q_v0), hl
        ld hl, (q_hi)
        ld (q_v1), hl
        jr er_q
er_v:   ld hl, (q_lo)
        ld (q_u0), hl
        ld hl, (q_hi)
        ld (q_u1), hl
        ld hl, (q_a)
        ld (q_v0), hl
        ld hl, (q_b)
        ld (q_v1), hl
er_q:   push ix
        call emit_quad
        pop ix
        ld de, 4
        add ix, de
        pop bc
        djnz er_1
        ret

uv_tu:      equ RAM + 0x46B
uv_tv:      equ RAM + 0x46C
q_a:        equ acc2
q_b:        equ acc2 + 2
q_lo:       equ p0
q_hi:       equ p0 + 2
q_u0:       equ p1
q_u1:       equ p1 + 2
q_v0:       equ p1 + 4
q_v1:       equ bx0

; the quad (q_u0, q_v0) (q_u1, q_v0) (q_u1, q_v1) (q_u0, q_v1) at height fp_n
emit_quad:
        call place_n
        ; the signs, once (into s_u0 .. s_v1; the q_ values are kept)
        ld hl, (q_u0)
        ld de, (q_u1)
        ld a, (fng_u)
        or a
        jr z, eqd_1
        call neg_hl
        ex de, hl
        call neg_hl
        ex de, hl
eqd_1:  ld (s_u0), hl
        ld (s_u1), de
        ld hl, (q_v0)
        ld de, (q_v1)
        ld a, (fng_v)
        or a
        jr z, eqd_2
        call neg_hl
        ex de, hl
        call neg_hl
        ex de, hl
eqd_2:  ld (s_v0), hl
        ld (s_v1), de
        ld hl, (s_u0)
        ld de, (s_v0)
        call put_uv_raw
        ld hl, (s_u1)
        ld de, (s_v0)
        call put_uv_raw
        ld hl, (s_u1)
        ld de, (s_v1)
        call put_uv_raw
        ld hl, (s_u0)
        ld de, (s_v1)
        ; (fall through)

s_u0:       equ RAM + 0x4D2
s_u1:       equ RAM + 0x4D4
s_v0:       equ RAM + 0x4D6
s_v1:       equ RAM + 0x4D8

; HL = u, DE = v (signs applied) into pt, then pt to geo3d
put_uv_raw:
        ld b, h
        ld c, l
        ld hl, (fst_u)
        ld (hl), c
        inc hl
        ld (hl), b
        ld hl, (fst_v)
        ld (hl), e
        inc hl
        ld (hl), d
        ld hl, pt
        ld bc, 6 * 256 + GEO_DAT
        otir
        ret

; fp_n into pt (its component, its sign)
place_n:
        ld hl, (fp_n)
        ld a, (fng_n)
        or a
        call nz, neg_hl
        ex de, hl
        ld hl, (fst_n)
        ld (hl), e
        inc hl
        ld (hl), d
        ret

; HL = u, DE = v into pt, then pt to geo3d (6 bytes)
put_uv_out:
        push de
        ld a, (fng_u)
        or a
        call nz, neg_hl
        ex de, hl
        ld hl, (fst_u)
        ld (hl), e
        inc hl
        ld (hl), d
        pop hl
        ld a, (fng_v)
        or a
        call nz, neg_hl
        ex de, hl
        ld hl, (fst_v)
        ld (hl), e
        inc hl
        ld (hl), d
        ld hl, pt
        ld bc, 6 * 256 + GEO_DAT
        otir
        ret

; the goal's two quads (heights from T mod 42): u, v = centre +- GB
emit_goal:
        ld a, (gl)
        call cell_uv                    ; HL = u centre, DE = v centre
        push de
        ld de, (lvc + LV_GB)
        push hl
        or a
        sbc hl, de
        ld (q_u0), hl
        pop hl
        add hl, de
        ld (q_u1), hl
        pop hl
        push hl
        or a
        sbc hl, de
        ld (q_v0), hl
        pop hl
        add hl, de
        ld (q_v1), hl
        ld a, (t42)
        add a, a
        ld hl, T_GOALH1
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld hl, (lvc + LV_KS)
        add hl, de
        ld (fp_n), hl
        call emit_quad
        ld a, (t42)
        add a, a
        ld hl, T_GOALH2
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld hl, (lvc + LV_KS)
        add hl, de
        ld (fp_n), hl
        jp emit_quad

; A = cell -> HL = (2c + 1 - lv) HG, DE = (2r + 1 - lv) HG
cell_uv:
        push af
        ld hl, cr
        call add_hl_a
        ld a, (hl)
        add a, a
        inc a
        ld hl, mlv
        sub (hl)
        call uh_of
        ex de, hl
        pop af
        ld hl, cc
        call add_hl_a
        ld a, (hl)
        add a, a
        inc a
        ld hl, mlv
        sub (hl)
        jp uh_of

; A = t (signed, -12..12) -> HL = t * HG (uh_tab)
uh_of:  add a, 12
        add a, a
        ld hl, uh_tab
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        ret

; (fp_n, fp_u, fp_v) on the face (set_fax) -> pt -> 6 bytes to geo3d
emit_point:
        call place_point
        ld hl, pt
        ld bc, 6 * 256 + GEO_DAT
        otir
        ret

; A = face: its axes (fax: 2 * component, negate, for n, u, v) and, for
; place_point, where each of n, u, v goes in pt and its sign
set_fax:
        ld b, a
        add a, a
        add a, b
        add a, a
        ld hl, T_FAXES
        call add_hl_a
        ld de, fax
        ld bc, 6
        ldir
        ld a, (fax + 0)
        ld hl, pt
        call add_hl_a
        ld (fst_n), hl
        ld a, (fax + 2)
        ld hl, pt
        call add_hl_a
        ld (fst_u), hl
        ld a, (fax + 4)
        ld hl, pt
        call add_hl_a
        ld (fst_v), hl
        ld a, (fax + 1)
        ld (fng_n), a
        ld a, (fax + 3)
        ld (fng_u), a
        ld a, (fax + 5)
        ld (fng_v), a
        ret

; (fp_n, fp_u, fp_v) on the face -> pt, without sending it
place_point:
        ld hl, (fp_n)
        ld a, (fng_n)
        or a
        call nz, neg_hl
        ex de, hl
        ld hl, (fst_n)
        ld (hl), e
        inc hl
        ld (hl), d
        ld hl, (fp_u)
        ld a, (fng_u)
        or a
        call nz, neg_hl
        ex de, hl
        ld hl, (fst_u)
        ld (hl), e
        inc hl
        ld (hl), d
        ld hl, (fp_v)
        ld a, (fng_v)
        or a
        call nz, neg_hl
        ex de, hl
        ld hl, (fst_v)
        ld (hl), e
        inc hl
        ld (hl), d
        ret

fst_n:      equ RAM + 0x47A
fst_u:      equ RAM + 0x47C
fst_v:      equ RAM + 0x47E
fng_n:      equ RAM + 0x480
fng_u:      equ RAM + 0x481
fng_v:      equ RAM + 0x482

; ----------------------------------------------------------------------------
; face streams: FADDR = HL, then the stream index
faces_at:
        ld a, 0x58
        ld b, 0x6C
        call g10
        ld a, 0x52
        out (GEO_IDX), a
        ret

; one face: fidx[0..3] (local indices) + cur_vb, BASE = A
emit_face:
        push af
        ld hl, fidx
        ld c, 0
        ld b, 4
ef_1:   ld e, (hl)
        inc hl
        ld d, (hl)
        inc hl
        push hl
        ld hl, (cur_vb)
        add hl, de
        ld a, l
        out (GEO_DAT), a
        ld a, h
        and 3
        rrca
        rrca                            ; the 2 high bits at 7-6
        srl c
        srl c
        or c
        ld c, a                         ; index k ends at bits 2k + 1, 2k
        pop hl
        djnz ef_1
        ld a, c
        out (GEO_DAT), a                ; H
        xor a
        ld b, 6
ef_4:   out (GEO_DAT), a                ; NX NY NZ
        djnz ef_4
        pop af
        out (GEO_DAT), a                ; BASE
        ret

; one quad face: local vertices HL .. HL + 3 (+ cur_vb), BASE = A
emit_qface:
        push af
        ld de, (cur_vb)
        add hl, de                      ; the first absolute index
        ld c, 0
        ld b, 4
eq_1:   ld a, l
        out (GEO_DAT), a
        ld a, h
        and 3
        rrca
        rrca
        srl c
        srl c
        or c
        ld c, a
        inc hl
        djnz eq_1
        ld a, c
        out (GEO_DAT), a                ; H
        xor a
        out (GEO_DAT), a
        out (GEO_DAT), a
        out (GEO_DAT), a
        out (GEO_DAT), a
        out (GEO_DAT), a
        out (GEO_DAT), a                ; NX NY NZ
        pop af
        out (GEO_DAT), a                ; BASE
        ret

; fidx = (HL, HL + 1, HL + 2, HL + 3)
quad_idx:
        ld (fidx), hl
        inc hl
        ld (fidx + 2), hl
        inc hl
        ld (fidx + 4), hl
        inc hl
        ld (fidx + 6), hl
        ret

; local index of the first mid vertex: NVF (+ 8 goal)
vm_of:  ld hl, (lvc + LV_NVF)
        ld a, (cur_goal)
        or a
        ret z
        ld de, 8
        add hl, de
        ret

; all the faces of the block
up_faces_all:
        ld hl, (cur_fb)
        call faces_at
        ; the floor: a = r (lv + 1) + c: (a, a + 1, a + lv + 2, a + lv + 1)
        ld b, 0
uf_r:   ld c, 0
uf_c:   push bc
        ld a, (mlv)
        inc a
        ld l, b
        ld h, 0
        call mul_hl_a                   ; r (lv + 1)
        pop bc
        push bc
        ld a, c
        call add_hl_a
        ld (fidx), hl
        inc hl
        ld (fidx + 2), hl
        ld a, (mlv)
        call add_hl_a
        ld (fidx + 6), hl
        inc hl
        ld (fidx + 4), hl
        ld a, 0x81
        call emit_face
        pop bc
        inc c
        ld a, (mlv)
        cp c
        jr nz, uf_c
        inc b
        cp b
        jr nz, uf_r
        jp uf_upper

; the faces from goal1 on (the colours change with the activity)
up_faces_upper:
        ld a, (nn)
        ld l, a
        ld h, 0
        ld de, (cur_fb)
        add hl, de
        call faces_at
uf_upper:
        ld a, (cur_goal)
        or a
        jr z, uf_m
        ld hl, (lvc + LV_NVF)
        call quad_idx
        ld a, (cur_act)
        or a
        ld a, C1
        jr z, uf_g1
        ld a, C2
uf_g1:  call emit_face
uf_m:   call vm_of                      ; the mids
        ld a, (cur_act)
        or a
        ld a, C1
        jr z, uf_m1
        ld a, C2
uf_m1:  call uf_runs
        ld a, (cur_goal)
        or a
        jr z, uf_t
        call goal2_face
uf_t:   call vm_of                      ; the tops: after the mids
        ld a, (cur_nr)
        add a, a
        add a, a
        call add_hl_a                   ; + 4 nr (nr < 64)
        ld a, (cur_act)
        or a
        ld a, C2
        jr z, uf_t1
        ld a, C7
uf_t1:  ; (fall through)

; nr quads from local vertex HL, BASE A
uf_runs:
        ld c, a
        ld a, (cur_nr)
        or a
        ret z
        ld b, a
ur_1:   push bc
        push hl
        ld a, c
        call emit_qface
        pop hl
        ld de, 4
        add hl, de
        pop bc
        djnz ur_1
        ret

goal2_face:
        ld hl, (lvc + LV_NVF)
        ld de, 4
        add hl, de
        call quad_idx
        ld a, (tick_t)
        and 4
        ld a, C3
        jr z, g2_1
        ld a, C6
g2_1:   jp emit_face

; the goal's moving parts: its 8 vertices and the goal2 face
up_goal:
        ld hl, (lvc + LV_NVF)
        ld de, (cur_vb)
        add hl, de
        call verts_at
        call emit_goal
        ; goal2's local face index: nn + 1 + nr
        ld a, (nn)
        inc a
        ld hl, cur_nr
        add a, (hl)
        ld l, a
        ld h, 0
        ld de, (cur_fb)
        add hl, de
        call faces_at
        jp goal2_face

; the floor faces' texture coordinates
up_uvs:
        ld hl, (cur_fb)
        ld a, 0x65
        ld b, 0x6E
        call g10
        ld a, 0x53
        out (GEO_IDX), a
        ld a, (lvc + LV_CW)
        ld d, a
        ld a, (lvc + LV_CH)
        ld e, a
        ld b, 0                         ; r * ch
        ld a, (mlv)
        ld h, a                         ; rows left
uu_r:   ld c, 0                         ; c * cw
        ld a, (mlv)
        ld l, a
uu_c:   ld a, c
        out (GEO_DAT), a
        ld a, b
        out (GEO_DAT), a
        ld a, c
        add a, d
        out (GEO_DAT), a
        ld a, b
        out (GEO_DAT), a
        ld a, c
        add a, d
        out (GEO_DAT), a
        ld a, b
        add a, e
        out (GEO_DAT), a
        ld a, c
        out (GEO_DAT), a
        ld a, b
        add a, e
        out (GEO_DAT), a
        ld a, c
        add a, d
        ld c, a
        dec l
        jr nz, uu_c
        ld a, b
        add a, e
        ld b, a
        dec h
        jr nz, uu_r
        ret

; ----------------------------------------------------------------------------
; the ball's point bm and its shadow's bsh (model units)
ball_points:
        ld a, (mv_on)
        or a
        jr nz, bp_mv
        ld a, (cur)
        ld de, bm
        call ball_cell
        jr bp_sh
bp_mv:  ld a, (mv_from)
        ld de, p0
        call ball_cell
        ld a, (mv_to)
        ld de, p1
        call ball_cell
        ; bm = p0 + (((p1 - p0) k + 8192) >> 14), k = K10[j]
        ld a, (mv_j)
        add a, a
        ld hl, T_K10
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        ld (tmp + 4), hl
        ld b, 0
bp_1:   push bc
        ld hl, p1
        ld a, b
        call add_hl_a
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld hl, p0
        ld a, b
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        push hl
        ex de, hl
        or a
        sbc hl, de                      ; p1 - p0
        ld de, (tmp + 4)
        call mulq14
        pop de
        add hl, de
        ex de, hl
        pop bc
        push bc
        ld hl, bm
        ld a, b
        call add_hl_a
        ld (hl), e
        inc hl
        ld (hl), d
        pop bc
        inc b
        inc b
        ld a, b
        cp 6
        jr c, bp_1
bp_sh:  ; bsh = bm - (bm >> 4) - (bm >> 7) (x 0.9297), arithmetic shifts
        ld ix, bm
        ld iy, bsh
        ld b, 3
bp_2:   push bc
        ld l, (ix + 0)
        ld h, (ix + 1)
        push hl
        ld b, 4
bp_3:   sra h
        rr l
        djnz bp_3                       ; v >> 4
        ex de, hl
        pop hl
        push hl
        or a
        sbc hl, de
        ex (sp), hl                     ; (sp) = v - (v >> 4), HL = v
        ld b, 7
bp_4:   sra h
        rr l
        djnz bp_4                       ; v >> 7
        ex de, hl
        pop hl
        or a
        sbc hl, de
        ld (iy + 0), l
        ld (iy + 1), h
        inc ix
        inc ix
        inc iy
        inc iy
        pop bc
        djnz bp_2
        ret

; A = cell, DE -> 3 words: its ball centre (at HBALL on the cell's face)
ball_cell:
        push de
        push af
        ld hl, cf
        call add_hl_a
        ld a, (hl)
        call set_fax
        pop af
        call cell_uv
        ld (fp_u), hl
        ld (fp_v), de
        ld hl, (lvc + LV_HBALL)
        ld (fp_n), hl
        call place_point
        pop de
        ld hl, pt
        ld bc, 6
        ldir
        ret

; ----------------------------------------------------------------------------
; the ball (LMMM from page 3, TIMP), then the walls near it in front of it
draw_ball:
        ; pr from the ball's depth
        ld hl, (b_pz)
        ld c, PR_MIN
        ld ix, lvc + LV_PRZ4
        ld b, 7
db_p1:  push hl
        ld e, (ix + 0)
        ld d, (ix + 1)
        ex de, hl
        or a
        sbc hl, de                      ; threshold - z >= 0 ?
        pop hl
        jr c, db_p2
        ld a, 11
        sub b                           ; p = 4 .. 10
        ld c, a
db_p2:  inc ix
        inc ix
        djnz db_p1
        ; T_BALLS + (pr - 3) * 24: the ball, then the shadow (6 words each)
        ld a, c
        sub PR_MIN
        ld l, a
        ld h, 0
        ld a, 24
        call mul_hl_a
        ld de, T_BALLS
        add hl, de
        push hl
        ld de, 12
        add hl, de
        ld de, (b_qx)
        ld bc, (b_qy)
        inc bc
        inc bc
        inc bc                          ; the shadow 3 lines lower
        call ball_copy
        pop hl
        ld de, (b_px)
        ld bc, (b_py)
        call ball_copy
        jp occ_out

; HL -> image (sx, sy, w, h, cx, cy); DE = x, BC = y of its centre
bi_sx:      equ tmp
bi_sy:      equ tmp + 2
bc_w:       equ acc2
bc_h:       equ acc2 + 2
bc_dx:      equ p0
bc_dy:      equ p0 + 2
bc_x0:      equ p0 + 4
bc_y0:      equ p1
ball_copy:
        push bc
        push de
        ld de, bi_sx
        ld bc, 4
        ldir                            ; sx, sy
        ld de, bc_w
        ld bc, 4
        ldir                            ; w, h
        ld e, (hl)
        inc hl
        ld d, (hl)                      ; cx
        inc hl
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a                         ; cy
        ex (sp), hl                     ; (sp) = cy, HL = x
        or a
        sbc hl, de
        ld (bc_dx), hl                  ; dx = x - cx
        pop de                          ; cy
        pop hl                          ; y
        or a
        sbc hl, de
        ld (bc_dy), hl                  ; dy = y - cy
        ; x0 = max(0, -dx), x1 = min(w, 512 - dx)
        ld hl, (bc_dx)
        call neg_hl
        bit 7, h
        jr z, bc_1
        ld hl, 0
bc_1:   ld (bc_x0), hl
        ld hl, 512
        ld de, (bc_dx)
        or a
        sbc hl, de
        ld de, (bc_w)
        call min_hl_de                  ; HL = x1
        ld de, (bc_x0)
        or a
        sbc hl, de                      ; nx = x1 - x0
        ret z
        bit 7, h
        ret nz
        push hl                         ; nx
        ld hl, (bc_dy)
        call neg_hl
        bit 7, h
        jr z, bc_2
        ld hl, 0
bc_2:   ld (bc_y0), hl
        ld hl, 212
        ld de, (bc_dy)
        or a
        sbc hl, de
        ld de, (bc_h)
        call min_hl_de
        ld de, (bc_y0)
        or a
        sbc hl, de                      ; ny
        pop bc                          ; BC = nx
        ret z
        bit 7, h
        ret nz
        push hl
        pop ix                          ; IX = ny
        ; source (sx + x0, sy + y0), destination (dx + x0, ypage + dy + y0)
        ld hl, (bi_sx)
        ld de, (bc_x0)
        add hl, de
        ld (cp_sx), hl
        ld hl, (bi_sy)
        ld de, (bc_y0)
        add hl, de
        ld (cp_sy), hl
        ld hl, (bc_dy)
        add hl, de
        ld a, (pg)
        add a, h
        ld d, a
        ld e, l                         ; DE = dy + y0 + 256 pg
        ld hl, (bc_dx)
        push de
        ld de, (bc_x0)
        add hl, de
        pop de
        ld a, 0x98                      ; LMMM, TIMP
        jp copy_cmd

; HL = min(HL, DE), signed
min_hl_de:
        push hl
        or a
        sbc hl, de
        pop hl
        jp pe, mhd_ov
        ret m
        ex de, hl
        ret
mhd_ov: ret p
        ex de, hl
        ret

; ----------------------------------------------------------------------------
; the walls of the visible faces owned by a cell at most 2 steps from the
; ball's cell(s), whose middle or top quad the original paints after the
; ball: painted again (their own quads, at V_SCRATCH / F_SCRATCH, one RUN)
; the occluders' output (after the ball): the same as the last frame's (the
; quads still in geo3d's scratch RAM): only the RUN; else the upload and RUN
occ_out:
        ld a, (occ_same)
        or a
        jp z, oc_emit
        ld a, (occ_n)
        or a
        ret z
        jp oc_run

; the search (no I/O: it runs while geo3d draws the first floor). The same
; camera, ball and maze as the last frame: nothing to do (occ_same = 1)
occ_search:
        call occ_sig_cmp
        ld a, 1
        jr z, oc_same
        xor a
oc_same:
        ld (occ_same), a
        or a
        ret nz
oc_new:
        ; the per-face cache: emptied when the matrix or the maze's size changed
        ld hl, mat
        ld de, oc_key
        ld b, 18
        call cmp_n
        jr nz, oc_k1
        ld a, (mlv)
        ld hl, oc_key + 18
        cp (hl)
        jr z, oc_k2
oc_k1:  ld hl, mat
        ld de, oc_key
        ld bc, 18
        ldir
        ld a, (mlv)
        ld (de), a
        xor a
        ld (oc_valid), a
oc_k2:
        ; near (nl): the cells at most 2 steps from the ball's cell (n2tab,
        ; built with the maze), then those from the cell it comes from;
        ; nflag[cell] == stamp: in nl (a new stamp each frame); nfaces: the
        ; faces with a cell in nl
        ld hl, stamp
        inc (hl)
        jr nz, oc_00
        inc (hl)                        ; (0 is never a stamp:
        ld hl, nflag                    ;  clear the table when it wraps)
        ld de, nflag + 1
        ld bc, 255
        ld (hl), 0
        ldir
oc_00:  xor a
        ld (nl_n), a
        ld (nfaces), a
        ld hl, flist
        ld de, 32
        ld b, 6
oc_01:  ld (hl), a
        add hl, de
        djnz oc_01
        ld a, (cur)
        call n2_add
        ld a, (mv_on)
        or a
        jr z, oc_0
        ld a, (mv_from)
        call n2_add
oc_0:   ; zb = pz - 512
        ld hl, (b_pz)
        ld de, -512
        add hl, de
        ld (b_zb), hl
        xor a
        ld (occ_n), a
        ret

; A = a face in view (the floors' order, the order of vis): its candidates,
; if the search is not the last frame's (occ_same) and a near cell is on it
occ_one:
        ld c, a
        ld a, (occ_same)
        or a
        ret nz
        ld a, c
        ld (cur_face), a
        ld hl, bitmask
        call add_hl_a
        ld a, (nfaces)
        and (hl)
        ret z
        jp occ_face

; Z: the signature (matrix, ball, its cells, the maze, the active face) is
; the last frame's; else it is stored as the new one
occ_sig_cmp:
        ld hl, mat
        ld de, osig_new
        ld bc, 18
        ldir
        ld hl, bm
        ld bc, 6
        ldir
        ld a, (cur)
        ld (de), a
        inc de
        ld a, (mv_on)
        ld (de), a
        inc de
        or a
        ld a, (mv_from)
        jr nz, os_1
        xor a
os_1:   ld (de), a
        inc de
        ld a, (stage)
        ld (de), a
        inc de
        ld a, (act)
        ld (de), a
        ld hl, osig_new
        ld de, osig
        ld b, 29
os_2:   ld a, (de)
        cp (hl)
        jr nz, os_3
        inc hl
        inc de
        djnz os_2
        ret                             ; Z
os_3:   ld hl, osig_new
        ld de, osig
        ld bc, 29
        ldir
        or 1                            ; NZ
        ret

osig:       equ RAM + 0x2B0             ; 30: the last signature
osig_new:   equ RAM + 0x2D0             ; 30: this frame's

; A = cell: its list in n2tab (count, cells) added to nl (new cells only)
n2_add: ld l, a
        ld h, 0
        ld d, h
        ld e, l
        add hl, hl
        add hl, hl
        add hl, hl                      ; x 8
        add hl, hl                      ; x 16
        or a
        sbc hl, de
        sbc hl, de                      ; x 14
        ld de, n2tab
        add hl, de
        ld b, (hl)
        inc hl
n2_1:   push bc
        ld a, (hl)
        inc hl
        push hl
        call near_add
        pop hl
        pop bc
        djnz n2_1
        ret

; A = cell: added to near (nflag) and nl, if new. Changes A, C, HL.
near_add:
        ld l, a
        ld h, nflag >> 8
        ld a, (stamp)
        cp (hl)
        ret z
        ld (hl), a
        ld c, l
        ld h, cf >> 8                   ; (cf is page-aligned)
        ld a, (hl)
        push af
        ld hl, bitmask
        call add_hl_a
        ld a, (nfaces)
        or (hl)
        ld (nfaces), a
        pop af                          ; the face's list: flist + 32 f
        rrca
        rrca
        rrca
        ld l, a
        ld h, 0
        ld de, flist
        add hl, de
        inc (hl)
        ld a, (hl)
        call add_hl_a
        ld (hl), c
        ld hl, nl
        ld a, (nl_n)
        call add_hl_a
        ld (hl), c
        ld hl, nl_n
        inc (hl)
        ret

bitmask:    db 1, 2, 4, 8, 16, 32, 64, 128
nl:         equ nfr                     ; 64: the near cells, BFS order
nfaces:     equ RAM + 0x48B
nl_n:       equ nfr_n
nl_lo:      equ nfr2_n
nl_hi:      equ nfr2                    ; (one byte)

; the candidates of cur_face: its cells in nl (BFS order), their walls.
; The terms that only depend on the matrix and the face (the A terms before
; zb, the tables t U, t V) are kept per face in oc_cache while the matrix and
; the maze's size stay the same (oc_key; oc_valid: a bit per face).
occ_face:
        ld a, (act)
        ld hl, cur_face
        cp (hl)
        ld a, 0
        jr nz, of_a
        inc a
of_a:   ld (cur_act), a
        ; HL = oc_cache + 64 f
        ld a, (cur_face)
        ld l, a
        ld h, 0
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl                      ; 64 f
        ld de, oc_cache
        add hl, de
        ld (oc_ent), hl
        ld a, (cur_face)
        ld hl, bitmask
        call add_hl_a
        ld a, (oc_valid)
        and (hl)
        jr z, of_new
        ; kept: the tables to mu_tab / mv_tab, the A terms
        ld hl, (oc_ent)
        ld de, 4
        add hl, de
        ld de, mu_tab
        ld bc, 26
        ldir
        ld de, mv_tab
        ld bc, 26
        ldir
        jp of_az
of_new: ld a, (oc_valid)
        or (hl)
        ld (oc_valid), a
        ld a, (cur_face)
        call set_fax
        ; A terms: TZ + ((mn H + 8192) >> 14) (then the bias, minus zb)
        ld a, (fax + 0)
        ld b, a
        ld a, (fax + 1)
        call mrow2                      ; HL = mn
        push hl
        ld de, (lvc + LV_HMID)
        call mulq14
        ld de, TZ
        add hl, de
        ex de, hl
        ld hl, (oc_ent)
        ld (hl), e
        inc hl
        ld (hl), d
        pop hl
        ld de, (lvc + LV_HTOP)
        call mulq14
        ld de, TZ
        add hl, de
        ex de, hl
        ld hl, (oc_ent)
        inc hl
        inc hl
        ld (hl), e
        inc hl
        ld (hl), d
        ; U, V = (s M[2][i] HG + 8192) >> 14; tables t U, t V for t = -6 .. 6
        ld a, (fax + 2)
        ld b, a
        ld a, (fax + 3)
        call mrow2
        ld de, (lvc + LV_HG)
        call mulq14
        ld de, mu_tab
        call t_table
        ld a, (fax + 4)
        ld b, a
        ld a, (fax + 5)
        call mrow2
        ld de, (lvc + LV_HG)
        call mulq14
        ld de, mv_tab
        call t_table
        ld hl, (oc_ent)
        ld de, 4
        add hl, de
        ex de, hl
        ld hl, mu_tab
        ld bc, 26
        ldir
        ld hl, mv_tab
        ld bc, 26
        ldir
of_az:  ; f_amid / f_atop = the kept terms - zb
        ld hl, (oc_ent)
        ld e, (hl)
        inc hl
        ld d, (hl)
        inc hl
        push hl
        ex de, hl
        ld de, (b_zb)
        or a
        sbc hl, de
        ld (f_amid), hl
        pop hl
        ld e, (hl)
        inc hl
        ld d, (hl)
        ex de, hl
        ld de, (b_zb)
        or a
        sbc hl, de
        ld (f_atop), hl
        ; biases, colours
        ld a, (cur_act)
        or a
        jr z, of_in
        ld hl, (f_amid)
        ld de, 307
        add hl, de
        ld (f_amid), hl
        ld hl, (f_atop)
        ld de, -307
        add hl, de
        ld (f_atop), hl
        ld a, C2
        ld (f_cmid), a
        ld a, C7
        ld (f_ctop), a
        jr of_w
of_in:  ld hl, (f_amid)
        ld de, 614
        add hl, de
        ld (f_amid), hl
        ld a, C1
        ld (f_cmid), a
        ld a, C2
        ld (f_ctop), a
of_w:   ; the near cells of this face (flist + 32 f: count, cells)
        ld a, (cur_face)
        rrca
        rrca
        rrca
        ld l, a
        ld h, 0
        ld de, flist
        add hl, de
        ld a, (hl)
        or a
        ret z
        ld b, a
        inc hl
of_c:   push bc
        ld c, (hl)                      ; C = cell
        inc hl
        push hl
        ld a, c
        ld hl, wcnt
        call add_hl_a
        ld a, (hl)
        or a
        jr z, of_cn
        ld b, a
        ld l, c
        ld h, 0
        add hl, hl
        ld de, wptr
        add hl, de
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        push hl
        pop ix
of_1:   push bc
        ; t = tU + tV (mu_tab, mv_tab within one page)
        ld a, (ix + 0)
        add a, a
        add a, (mu_tab & 0xFF) + 12
        ld l, a
        ld h, mu_tab >> 8
        ld e, (hl)
        inc hl
        ld d, (hl)
        ld a, (ix + 1)
        add a, a
        add a, (mv_tab & 0xFF) + 12
        ld l, a
        ld h, mv_tab >> 8
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        add hl, de
        ld (f_t), hl
        ld de, (f_amid)
        add hl, de                      ; < 0: in front
        bit 7, h
        jr z, of_t1
        ld a, (f_cmid)
        ld c, 0
        call occ_add
of_t1:  ld hl, (f_t)
        ld de, (f_atop)
        add hl, de
        bit 7, h
        jr z, of_t2
        ld a, (f_ctop)
        ld c, 1
        call occ_add
of_t2:  ld de, 4
        add ix, de
        pop bc
        djnz of_1
of_cn:  pop hl
        pop bc
        djnz of_c
        ret

f_t:        equ RAM + 0x484
oc_cache:   equ 0xF000              ; 6 x 64: per face A mid, A top, t U (26), t V (26)
oc_key:     equ 0xF180              ; 19: the matrix and mlv the cache was made for
oc_valid:   equ 0xF193              ; a bit per face
oc_ent:     equ 0xF194              ; 2: this face's entry
occ_same:   equ RAM + 0x4E8
df_first:   equ RAM + 0x4E9
oe_last:    equ RAM + 0x4EA             ; 4: face, tu, tv, d of the last emitted
oe_newc:    equ RAM + 0x4EE
oe_face:    equ RAM + 0x486
of_ci:      equ RAM + 0x479

; B = 2 * component, A = negate -> HL = +-M[2][i] (mat + 12 + B)
mrow2:  push af
        ld a, b
        ld hl, mat + 12
        call add_hl_a
        ld a, (hl)
        inc hl
        ld h, (hl)
        ld l, a
        pop af
        or a
        ret z
        jp neg_hl

; HL = x: the table at DE of t * x (words) for t = -6 .. 6
t_table:
        push de
        ex de, hl
        ld hl, 0
        ld b, 6
tt_1:   or a
        sbc hl, de
        djnz tt_1
        ex (sp), hl                     ; (sp) = -6 x, HL = table
        pop bc                          ; BC = -6 x
        ex de, hl                       ; DE = table, HL = x
        ld a, 13
tt_2:   ex de, hl
        ld (hl), c
        inc hl
        ld (hl), b
        inc hl
        ex de, hl
        push hl
        add hl, bc
        ld b, h
        ld c, l
        pop hl
        dec a
        jr nz, tt_2
        ret

; HL < 0 (signed: the wall's layer in front of the ball): an occluder (A =
; colour, C = layer) for the wall at IX (tu, tv, ci, d)
occ_add:
        bit 7, h
        ret z
        ld (tmp + 4), a
        ld a, (occ_n)
        cp N_SCRATCH
        ret nc
        ld l, a
        inc a
        ld (occ_n), a
        ld h, 0
        add hl, hl
        add hl, hl
        add hl, hl
        ld de, occ
        add hl, de
        ld a, (cur_face)
        ld (hl), a
        inc hl
        ld (hl), c                      ; layer
        inc hl
        ld a, (tmp + 4)
        ld (hl), a                      ; colour
        inc hl
        ld a, (ix + 0)
        ld (hl), a                      ; tu
        inc hl
        ld a, (ix + 1)
        ld (hl), a                      ; tv
        inc hl
        ld a, (ix + 3)
        ld (hl), a                      ; d
        ret

; acc += (HL), 32 bits
add32_r:
        ex de, hl
        ld hl, acc
        jp add32_to

; the occluders' vertices, faces and RUN
oc_emit:
        ld a, (occ_n)
        or a
        ret z
        ld hl, V_SCRATCH
        call verts_at
        ld a, (occ_n)
        ld b, a
        ld ix, occ
        ld a, 0xFF
        ld (oe_face), a
        ld (oe_last), a
oe_1:   push bc
        ld a, (ix + 0)
        ld hl, oe_face
        cp (hl)
        jr z, oe_0
        ld (hl), a
        call set_fax
oe_0:   ; the same wall as the last one (its other layer): the same corners
        ld hl, oe_last + 1
        ld a, (ix + 3)
        cp (hl)
        jr nz, oe_new
        inc hl
        ld a, (ix + 4)
        cp (hl)
        jr nz, oe_new
        inc hl
        ld a, (ix + 5)
        cp (hl)
        jr nz, oe_new
        ld a, (oe_last)
        cp (ix + 0)
        jr z, oe_same
oe_new: ld a, (ix + 0)
        ld (oe_last), a
        ld a, (ix + 3)
        ld (oe_last + 1), a
        ld a, (ix + 4)
        ld (oe_last + 2), a
        ld a, (ix + 5)
        ld (oe_last + 3), a
        ld a, 1
        jr oe_h0
oe_same:
        xor a
oe_h0:  ld (oe_newc), a
        ; height
        ld hl, (lvc + LV_HMID)
        ld a, (ix + 1)
        or a
        jr z, oe_h
        ld hl, (lvc + LV_HTOP)
oe_h:   ld (fp_n), hl
        ld a, (oe_newc)
        or a
        jr z, oe_q
        ; su, sv: d odd: (WW, WL), else (WL, WW)
        ld hl, (lvc + LV_WW)
        ld de, (lvc + LV_WL)
        bit 0, (ix + 5)
        jr nz, oe_s
        ex de, hl
oe_s:   ld (tmp), hl                    ; su
        ld (tmp + 2), de                ; sv
        ld a, (ix + 3)
        call uh_of
        push hl
        ld de, (tmp)
        or a
        sbc hl, de
        ld (q_u0), hl
        pop hl
        add hl, de
        ld (q_u1), hl
        ld a, (ix + 4)
        call uh_of
        push hl
        ld de, (tmp + 2)
        or a
        sbc hl, de
        ld (q_v0), hl
        pop hl
        add hl, de
        ld (q_v1), hl
oe_q:   push ix
        call emit_quad
        pop ix
        ld de, 8
        add ix, de
        pop bc
        dec b
        jp nz, oe_1
        ; faces: (4k .. 4k + 3) + V_SCRATCH
        ld hl, F_SCRATCH
        call faces_at
        ld hl, V_SCRATCH
        ld (cur_vb), hl
        ld a, (occ_n)
        ld b, a
        ld ix, occ
        ld hl, 0
oe_2:   push bc
        push hl
        ld a, (ix + 2)
        call emit_qface
        pop hl
        ld de, 4
        add hl, de
        ld de, 8
        add ix, de
        pop bc
        djnz oe_2
oc_run: ld hl, V_SCRATCH
        ld a, 0x54
        ld b, 0x55
        call g10
        ld a, (occ_n)
        add a, a
        add a, a
        ld l, a
        ld h, 0
        ld a, 0x42
        ld b, 0x6A
        call g10
        ld hl, F_SCRATCH
        ld a, 0x56
        ld b, 0x57
        call g10
        ld a, (occ_n)
        ld l, a
        ld h, 0
        ld a, 0x59
        ld b, 0x6D
        call g10
        jp geo_run

; ----------------------------------------------------------------------------
; the twelve floor textures of the maze (page 3): Machine.bake
bk_sx:      equ RAM + 0x460             ; 2
bk_sy:      equ RAM + 0x462             ; 2
bk_dith:    equ RAM + 0x464
bk_act:     equ RAM + 0x465
tr_col:     equ RAM + 0x466
tr_x0:      equ RAM + 0x467
tr_x1:      equ RAM + 0x468
tr_y0:      equ RAM + 0x469
tr_y1:      equ RAM + 0x46A
bake:
        ld a, TBANK3
        call setbank
        ; uh_tab for this size (t * HG, t = -12 .. 12)
        ld hl, (lvc + LV_HG)
        call neg_hl
        ld de, (lvc + LV_HG)
        ; -12 HG
        push de
        ld b, 12
        ld hl, 0
bk_u0:  or a
        sbc hl, de
        djnz bk_u0
        pop de
        ld ix, uh_tab
        ld b, 25
bk_u1:  ld (ix + 0), l
        ld (ix + 1), h
        inc ix
        inc ix
        add hl, de
        djnz bk_u1
        xor a
        ld (cur_face), a
bk_f:   xor a
bk_a:   ld (bk_act), a
        ; slot s = 2 f + active: x = (s & 3) * 128, y = TEX_Y + (s >> 2) * 64
        ld a, (cur_face)
        add a, a
        ld hl, bk_act
        add a, (hl)
        ld b, a
        and 3
        ld l, 0
        ld h, a
        srl h
        rr l                            ; * 128
        ld (bk_sx), hl
        ld a, b
        srl a
        srl a
        ld l, a
        ld h, 0
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        add hl, hl
        ld de, TEX_Y
        add hl, de
        ld (bk_sy), hl
        ld a, (bk_act)
        or a
        ld a, DITH_GREY
        jr z, bk_d
        ld a, DITH_ACT
bk_d:   ld (bk_dith), a
        ; the background of the slot
        ld hl, (bk_sx)
        ld de, (bk_sy)
        ld bc, 128
        ld ix, 64
        ld a, C1 * 17
        call hmmv
        ; the cells
        ld b, 0
bk_r:   ld c, 0
bk_c:   call ci_of
        ld hl, st
        cp (hl)
        ld e, C5
        jr z, bk_c1
        ld hl, gl
        cp (hl)
        ld e, C3
        jr z, bk_c1
        ld a, (bk_dith)
        ld e, a
bk_c1:  ; t = 2c + 1 - lv, 2r + 1 - lv; kinds C43, C43
        push bc
        ld a, c
        add a, a
        inc a
        ld hl, mlv
        sub (hl)
        ld d, a                         ; tu
        ld a, b
        add a, a
        inc a
        sub (hl)
        ld b, d
        ld c, a                         ; B = tu, C = tv
        ld d, 0                         ; kind x
        ld a, e
        ld e, 0                         ; kind y
        call tex_rect
        pop bc
        inc c
        ld a, (mlv)
        cp c
        jr nz, bk_c
        inc b
        cp b
        jr nz, bk_r
        ; the edges: passages and walls' shadows
        ld b, 0
bk_er:  ld c, 0
bk_ec:  call ci_of
        ld hl, grid
        call add_hl_a
        ld a, (hl)
        ld (tmp + 1), a
        xor a
bk_ed:  ld (tmp + 2), a
        cp 2
        jr c, bk_e1
        cp 3
        jr z, bk_e3
        ld a, (mlv)
        dec a
        cp b
        jr nz, bk_en
        jr bk_e1
bk_e3:  ld a, c
        or a
        jr nz, bk_en
bk_e1:  push bc
        call wall_t                     ; D = tu, E = tv
        ld a, (tmp + 2)
        ld l, a
        inc l
        ld a, (tmp + 1)
bk_e2:  rrca
        dec l
        jr nz, bk_e2
        ld b, d
        ld c, e
        ld a, (tmp + 2)
        jr nc, bk_wall
        ; a passage: d odd (P10, P36), else (P36, P10), the dither
        rrca
        ld d, 1
        ld e, 2
        jr c, bk_p1
        ld d, 2
        ld e, 1
bk_p1:  ld a, (bk_dith)
        call tex_rect
        jr bk_e9
bk_wall:
        rrca
        ld d, 3
        ld e, 4
        jr c, bk_w1
        ld d, 4
        ld e, 3
bk_w1:  ld a, C1
        call tex_rect
bk_e9:  pop bc
bk_en:  ld a, (tmp + 2)
        inc a
        cp 4
        jr c, bk_ed
        inc c
        ld a, (mlv)
        cp c
        jr nz, bk_ec
        inc b
        cp b
        jr nz, bk_er
        ; the goal's base
        ld a, (gl_face)
        ld hl, cur_face
        cp (hl)
        jr nz, bk_nx
        ld a, (gl)
        ld hl, cc
        call add_hl_a
        ld a, (hl)
        add a, a
        inc a
        ld hl, mlv
        sub (hl)
        ld b, a
        ld a, (gl)
        ld hl, cr
        call add_hl_a
        ld a, (hl)
        add a, a
        inc a
        ld hl, mlv
        sub (hl)
        ld c, a
        ld d, 5
        ld e, 5
        ld a, C1
        call tex_rect
bk_nx:  ld a, (bk_act)
        inc a
        cp 2
        jp c, bk_a
        ld a, (cur_face)
        inc a
        ld (cur_face), a
        cp 6
        jp c, bk_f
        ret

; a rectangle of the texture: B = tu, C = tv (half cells), D = kind of x,
; E = kind of y (0 C43, 1 P10, 2 P36, 3 WW, 4 WL, 5 GB), A = colour.
; (x0, x1) = TX[kind][t], (y0, y1) = TY[kind][t]; LMMV when not empty
tex_rect:
        ld (tr_col), a
        push de
        ld a, d
        ld e, b
        ld hl, (lvc + LV_PTX)
        call tr_ent
        ld a, (hl)
        ld (tr_x0), a
        inc hl
        ld a, (hl)
        ld (tr_x1), a
        pop de
        ld a, e
        ld e, c
        ld hl, (lvc + LV_PTY)
        call tr_ent
        ld a, (hl)
        ld (tr_y0), a
        inc hl
        ld a, (hl)
        ld (tr_y1), a
        ld a, (tr_x1)
        ld hl, tr_x0
        sub (hl)
        ret z
        ret c
        ld c, a
        ld b, 0                         ; BC = nx
        ld a, (tr_y1)
        ld hl, tr_y0
        sub (hl)
        ret z
        ret c
        push bc
        ld l, a
        ld h, 0
        push hl
        pop ix                          ; IX = ny
        ld a, (tr_y0)
        ld hl, (bk_sy)
        call add_hl_a
        ex de, hl                       ; DE = y
        ld a, (tr_x0)
        ld hl, (bk_sx)
        call add_hl_a                   ; HL = x
        pop bc
        ld a, (tr_col)
        jp lmmv

; A = kind, E = t (signed), HL = table: HL -> entry (kind * (2 lv + 1) + t + lv) * 2
tr_ent: push hl
        push de
        ld l, a
        ld h, 0
        ld a, (mlv)
        add a, a
        inc a
        call mul_hl_a                   ; (changes DE, B)
        pop de
        ld a, (mlv)
        add a, e
        call add_hl_a
        add hl, hl
        pop de
        add hl, de
        ret
