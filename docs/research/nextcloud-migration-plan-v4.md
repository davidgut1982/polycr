# Nextcloud Migration Plan — v4 Target Structure

**Instance:** https://nextcloud.shifting-ground.link  
**User:** david.gutowsky  
**WebDAV Base:** `https://nextcloud.shifting-ground.link/remote.php/dav/files/david.gutowsky`  
**Status:** PLAN ONLY — no operations executed  
**Date:** 2026-04-12  

---

## Conventions

- All paths are relative to the WebDAV base URL above.
- MKDIR = `MKCOL` request against the full WebDAV URL.
- MOVE = `MOVE` request with `Destination:` header pointing to the full target URL.
- Operations within each phase are sequenced: earlier numbers must complete before later ones that depend on them.
- Items marked **[VERIFY]** require a manual directory listing or content check before executing.
- Items marked **[WARNING]** have a known risk that must be resolved before execution.
- Items marked **[SKIP IF EMPTY]** should be confirmed non-empty before issuing the MOVE.

---

## Phase 0 — Pre-Flight Checks (Manual, No Operations)

Before executing any phase:

1. Confirm Duplicati backup job targeting `/Backup/openclaw/` (or its predecessor path) is **paused or reconfigured** before Phase 5 operation #5-01. Duplicati will fail or corrupt if its target directory is moved while it is active.
2. Confirm no sync clients (desktop, mobile) are actively syncing during the migration window to prevent conflict files.
3. Take a snapshot or verify a recent backup exists of the full Nextcloud data directory.
4. Do a top-level PROPFIND listing of the WebDAV root to confirm actual directory names match the names used in this plan. Names with spaces and special characters are particularly risky (e.g., `/moto backup/`, `/Personal/David Gutowsky/`, `/Backup/FOUND.000/`).

---

## Phase 1 — Create All Target Directories

All destination directories must exist before any MOVE operation. No source content is touched in this phase.

Ordering within Phase 1 is parent-before-child.

### 1-A: New top-level directories

| # | Operation | Path |
|---|-----------|------|
| 1-A-01 | MKDIR | `/Inbox/` |
| 1-A-02 | MKDIR | `/Civic/` |
| 1-A-03 | MKDIR | `/Hobbies/` |
| 1-A-04 | MKDIR | `/IT/` |
| 1-A-05 | MKDIR | `/Media/` |
| 1-A-06 | MKDIR | `/Backup/` |
| 1-A-07 | MKDIR | `/Archive/` |

> Note: `/Personal/` already exists (source data lives there); do not re-create it.

### 1-B: Second-level directories under /Personal/

| # | Operation | Path |
|---|-----------|------|
| 1-B-01 | MKDIR | `/Personal/Identity/` |
| 1-B-02 | MKDIR | `/Personal/Identity/Latvian-Citizenship/` |
| 1-B-03 | MKDIR | `/Personal/Health/` |
| 1-B-04 | MKDIR | `/Personal/Financial/` |
| 1-B-05 | MKDIR | `/Personal/Financial/Taxes/` |
| 1-B-06 | MKDIR | `/Personal/Financial/Credit-Cards/` |
| 1-B-07 | MKDIR | `/Personal/Financial/Student-Loans/` |
| 1-B-08 | MKDIR | `/Personal/Financial/Receipts/` |
| 1-B-09 | MKDIR | `/Personal/Insurance/` |
| 1-B-10 | MKDIR | `/Personal/Legal/` |
| 1-B-11 | MKDIR | `/Personal/Housing/` |
| 1-B-12 | MKDIR | `/Personal/Housing/3322-Chukar/` |
| 1-B-13 | MKDIR | `/Personal/Housing/10810-Pheasant/` |
| 1-B-14 | MKDIR | `/Personal/Housing/Lease-Agreements/` |
| 1-B-15 | MKDIR | `/Personal/Housing/Manuals/` |

### 1-C: Second-level directories under /Civic/

| # | Operation | Path |
|---|-----------|------|
| 1-C-01 | MKDIR | `/Civic/McHenry-County/` |
| 1-C-02 | MKDIR | `/Civic/Greenwood-Township/` |
| 1-C-03 | MKDIR | `/Civic/MCED/` |
| 1-C-04 | MKDIR | `/Civic/DNC/` |
| 1-C-05 | MKDIR | `/Civic/Politics/` |

### 1-D: Second-level directories under /Hobbies/

| # | Operation | Path |
|---|-----------|------|
| 1-D-01 | MKDIR | `/Hobbies/Bicycle/` |
| 1-D-02 | MKDIR | `/Hobbies/Solar/` |
| 1-D-03 | MKDIR | `/Hobbies/Hashing/` |
| 1-D-04 | MKDIR | `/Hobbies/Conan/` |
| 1-D-05 | MKDIR | `/Hobbies/Design-Plans/` |
| 1-D-06 | MKDIR | `/Hobbies/Recipes/` |

### 1-E: Second-level directories under /IT/

| # | Operation | Path |
|---|-----------|------|
| 1-E-01 | MKDIR | `/IT/Shifting-Ground/` |
| 1-E-02 | MKDIR | `/IT/Scripts/` |
| 1-E-03 | MKDIR | `/IT/Recovery-Codes/` |
| 1-E-04 | MKDIR | `/IT/Software-Licenses/` |
| 1-E-05 | MKDIR | `/IT/OpenVPN/` |

### 1-F: Second-level directories under /Media/

| # | Operation | Path |
|---|-----------|------|
| 1-F-01 | MKDIR | `/Media/Photos/` |
| 1-F-02 | MKDIR | `/Media/Music/` |
| 1-F-03 | MKDIR | `/Media/Movies/` |
| 1-F-04 | MKDIR | `/Media/Home-Videos/` |
| 1-F-05 | MKDIR | `/Media/Books/` |

### 1-G: Second-level directories under /Backup/

| # | Operation | Path |
|---|-----------|------|
| 1-G-01 | MKDIR | `/Backup/openclaw/` |

### 1-H: Second-level directories under /Archive/

| # | Operation | Path |
|---|-----------|------|
| 1-H-01 | MKDIR | `/Archive/IFMC/` |
| 1-H-02 | MKDIR | `/Archive/Old-Backups/` |
| 1-H-03 | MKDIR | `/Archive/Moto-Backup/` |
| 1-H-04 | MKDIR | `/Archive/Old-Gmail/` |
| 1-H-05 | MKDIR | `/Archive/Adobe-Config/` |
| 1-H-06 | MKDIR | `/Archive/Notes/` |

---

## Phase 2 — Archive Moves (Cold Storage First)

Clears top-level clutter and moves cold data before reorganizing active directories. All destination directories from Phase 1 must be created before executing this phase.

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 2-01 | `/IFMC/` | `/Archive/IFMC/` | **[VERIFY]** Confirm `/IFMC/` exists at root and is the correct folder before moving. |
| 2-02 | `/Upload/` (entire directory) | `/Archive/IFMC/` | **[VERIFY]** Confirm this contains IFMC design files, not general uploads. If it contains mixed content, do not bulk-move — sort manually first. |
| 2-03 | `/moto backup/` | `/Archive/Moto-Backup/` | **[VERIFY]** Directory name contains a space; confirm exact spelling via PROPFIND before issuing MOVE. |
| 2-04 | `/configuration/` | `/Archive/Adobe-Config/` | **[VERIFY]** Confirm this is Adobe configuration data and not some other app config. |
| 2-05 | `/Personal/Old Gmail Files/` | `/Archive/Old-Gmail/` | Prerequisite: Phase 1 complete. |
| 2-06 | `/Backup/FOUND.000/` | `/Archive/Old-Backups/` | **[VERIFY]** Confirm subdirectory exists under `/Backup/` before moving. |
| 2-07 | `/Backup/Programs/` | `/Archive/Old-Backups/` | |
| 2-08 | `/Backup/Shared Documents/` | `/Archive/Old-Backups/` | |
| 2-09 | `/Backup/david@ifmc-1.co/` | `/Archive/Old-Backups/` | |
| 2-10 | `/Backup/genna dumb phone/` | `/Archive/Old-Backups/` | **[VERIFY]** Directory name contains spaces; confirm exact spelling. |
| 2-11 | `/Backup/silver usb/` | `/Archive/Old-Backups/` | **[VERIFY]** Directory name contains spaces; confirm exact spelling. |
| 2-12 | Loose files in `/Backup/` root (BOOTEX.LOG, Car MPG.xls, etc.) | `/Archive/Old-Backups/` | **[VERIFY]** Do a PROPFIND on `/Backup/` and identify all loose files individually. Issue one MOVE per file. Do NOT move the `/Backup/openclaw/` directory created in Phase 1 or any subdirectory that should remain under `/Backup/`. |
| 2-13 | `/Notes/Fitness TRT/` | `/Archive/Notes/` | Prerequisite: `/Notes/` flat .md files stay in place — only subdirectories listed here are moved. |
| 2-14 | `/Notes/IT/` | `/Archive/Notes/` | |
| 2-15 | `/Notes/Latvian Lessons/` | `/Archive/Notes/` | |
| 2-16 | `/Notes/medical/` | `/Archive/Notes/` | |
| 2-17 | `/Notes/Machines/` | `/Archive/Notes/` | |

---

## Phase 3 — Personal Reorganization

Reorganizes content within and out of `/Personal/`. Must run after Phase 1 (all target dirs exist) and after Phase 2 (Old Gmail already moved).

Children of `/Personal/David Gutowsky/` are moved first (3-A), then the parent subdirectory remainder (3-B), then other `/Personal/` subdirectories (3-C), then the Civic/Hobbies/IT splits (3-D).

### 3-A: Move children of /Personal/David Gutowsky/ first

These must be moved before any attempt to move `/Personal/David Gutowsky/` itself.

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 3-A-01 | `/Personal/David Gutowsky/Credit Cards/` | `/Personal/Financial/Credit-Cards/` | **[VERIFY]** Confirm exact directory name including spaces. |
| 3-A-02 | `/Personal/David Gutowsky/Student Loans/` | `/Personal/Financial/Student-Loans/` | |
| 3-A-03 | `/Personal/David Gutowsky/Medical/` | `/Personal/Health/` | **[VERIFY]** Confirm no existing content in `/Personal/Health/` to avoid collision. Health/ was just created in Phase 1 so should be empty. |
| 3-A-04 | `/Personal/David Gutowsky/Therapy/` | `/Personal/Health/` | **[VERIFY]** Therapy subdir will land inside `/Personal/Health/Therapy/` — confirm this is intended vs. flattening its contents. |
| 3-A-05 | `/Personal/David Gutowsky/Latvia Citizenship/` | `/Personal/Identity/Latvian-Citizenship/` | **[VERIFY]** Confirm exact name — "Latvia Citizenship" vs. "Latvian Citizenship". |
| 3-A-06 | `/Personal/David Gutowsky/Latvian Passport - eID/` | `/Personal/Identity/Latvian-Citizenship/` | **[VERIFY]** Both 3-A-05 and 3-A-06 go into the same target. Confirm no name collision between the two source folders' contents. |
| 3-A-07 | `/Personal/David Gutowsky/Signature/` | `/Personal/Identity/Signature/` | Target directory `/Personal/Identity/Signature/` does not appear in Phase 1 MKDIR list — **[WARNING]** create it first: MKDIR `/Personal/Identity/Signature/` |
| 3-A-08 | `/Personal/David Gutowsky/wallet/` | `/Personal/Identity/wallet/` | **[WARNING]** create target first: MKDIR `/Personal/Identity/wallet/` |
| 3-A-09 | `/Personal/David Gutowsky/Travel/` | `/Personal/Travel/` | **[WARNING]** create target first: MKDIR `/Personal/Travel/` |
| 3-A-10 | Loose files in `/Personal/David Gutowsky/` (passports, SSN, licenses, marriage cert, I-9, insurance cards) | `/Personal/Identity/` | **[VERIFY]** Do a PROPFIND on `/Personal/David Gutowsky/` after all subdirs above have been moved. Move each remaining loose file individually into `/Personal/Identity/`. Confirm no subdirectories remain before bulk-moving. |

> After 3-A-10, `/Personal/David Gutowsky/` should be empty and can be deleted (rmdir / MKCOL-with-DELETE or leave empty). Confirm before deleting.

### 3-B: Move other /Personal/ subdirectories

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 3-B-01 | `/Personal/Taxes/` | `/Personal/Financial/Taxes/` | |
| 3-B-02 | `/Personal/Insurance/` | `/Personal/Insurance/` | **[VERIFY]** Source and destination share the same name but different parent. Confirm this is a structural rename only (moving from direct child of Personal to new Insurance/ created in Phase 1). |
| 3-B-03 | `/Personal/Genna Sue Hibbs/` | `/Personal/Legal/Genna/` | **[WARNING]** create target first: MKDIR `/Personal/Legal/Genna/` |
| 3-B-04 | `/Personal/Auto/` | `/Personal/Auto/` | **[VERIFY]** Source and target appear identical (both `/Personal/Auto/`). Confirm if this is a no-op or if a rename/move is intended. If no-op, skip. |
| 3-B-05 | `/Personal/10810 Pheasant Lane/` | `/Personal/Housing/10810-Pheasant/` | **[VERIFY]** Confirm exact source directory name including spaces. |
| 3-B-06 | `/Personal/3322 Chukar Pl/` | `/Personal/Housing/3322-Chukar/` | **[VERIFY]** Confirm exact source name. |
| 3-B-07 | `/Personal/Lease Agreements/` | `/Personal/Housing/Lease-Agreements/` | |
| 3-B-08 | `/Personal/Manuals/` | `/Personal/Housing/Manuals/` | |
| 3-B-09 | `/Personal/Theodore-Cooper-Gutowsky/` | `/Personal/Theodore/` | **[WARNING]** create target first: MKDIR `/Personal/Theodore/` |
| 3-B-10 | `/Personal/School Documents/` | `/Personal/School/` | **[WARNING]** create target first: MKDIR `/Personal/School/` |
| 3-B-11 | `/Personal/Job/` | `/Personal/Job/` | **[VERIFY]** Same as 3-B-04 — source and target look identical. Confirm if this is a no-op. If no-op, skip. |
| 3-B-12 | `/Personal/Recipts/` | `/Personal/Financial/Receipts/` | Note: source name is misspelled ("Recipts"). |
| 3-B-13 | `/Personal/rebates/` | `/Personal/Financial/Receipts/` | **[VERIFY]** Both 3-B-12 and 3-B-13 merge into `/Personal/Financial/Receipts/`. If both source directories contain files, move contents individually to avoid overwrite collisions. |
| 3-B-14 | `/Personal/Voicemails/` | `/Personal/Voicemails/` | **[VERIFY]** Again appears to be same path. Confirm intent — if no move is needed, skip. |
| 3-B-15 | `/Hibbs Law/` | `/Personal/Legal/Hibbs-Law/` | **[WARNING]** create target first: MKDIR `/Personal/Legal/Hibbs-Law/` — Source is at the ROOT level, not under `/Personal/`. |

### 3-C: Delete empty placeholder

| # | Operation | Path | Notes |
|---|-----------|------|-------|
| 3-C-01 | DELETE (if empty) | `/Personal/Latvian/` | **[VERIFY]** Confirm directory is empty before deleting. If it contains files, they need to be classified and routed. |

### 3-D: Civic, Hobbies, IT splits (out of /Personal/Government/, /Personal/Hobbies/, /Personal/IT/)

Move each subdirectory individually to avoid accidentally moving the parent before its children.

**Civic (from /Personal/Government/):**

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 3-D-01 | `/Personal/Government/McHenry County/` | `/Civic/McHenry-County/` | **[VERIFY]** Confirm exact source subdirectory name. |
| 3-D-02 | `/Personal/Government/Greenwood Township/` | `/Civic/Greenwood-Township/` | |
| 3-D-03 | `/Personal/Government/MCED/` | `/Civic/MCED/` | |
| 3-D-04 | `/Personal/Government/DNC/` | `/Civic/DNC/` | |
| 3-D-05 | `/Personal/Government/politics/` | `/Civic/Politics/` | **[VERIFY]** Confirm case: "politics" vs. "Politics". |
| 3-D-06 | DELETE `/Personal/Government/` (if empty) | — | **[VERIFY]** Confirm all subdirs removed before deleting parent. Do a PROPFIND to verify empty. |

**Hobbies (from /Personal/Hobbies/):**

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 3-D-07 | `/Personal/Hobbies/Bicycle/` | `/Hobbies/Bicycle/` | |
| 3-D-08 | `/Personal/Hobbies/Conan/` | `/Hobbies/Conan/` | |
| 3-D-09 | `/Personal/Hobbies/Design Plans/` | `/Hobbies/Design-Plans/` | **[VERIFY]** Confirm source name "Design Plans" with space. |
| 3-D-10 | `/Personal/Hobbies/Hashing/` | `/Hobbies/Hashing/` | |
| 3-D-11 | `/Personal/Hobbies/solar/` | `/Hobbies/Solar/` | **[VERIFY]** Confirm case: "solar" vs. "Solar". |
| 3-D-12 | DELETE `/Personal/Hobbies/` (if empty) | — | **[VERIFY]** Confirm all subdirs removed before deleting. |

**IT (from /Personal/IT/):**

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 3-D-13 | `/Personal/IT/Computer Scripts/` | `/IT/Scripts/` | **[VERIFY]** Confirm exact source subdir name. |
| 3-D-14 | `/Personal/IT/OpenVPN/` | `/IT/OpenVPN/` | |
| 3-D-15 | `/Personal/IT/Recovery Codes/` | `/IT/Recovery-Codes/` | **[VERIFY]** Confirm source name "Recovery Codes" with space. |
| 3-D-16 | `/Personal/IT/Software Licenses/` | `/IT/Software-Licenses/` | **[VERIFY]** Confirm source name. |
| 3-D-17 | DELETE `/Personal/IT/` (if empty) | — | **[VERIFY]** Confirm all subdirs removed before deleting. |

---

## Phase 4 — Top-Level Reorganization

Moves remaining top-level directories into their target locations under `/Media/`, `/IT/`, `/Hobbies/`. Must run after Phase 3 (which frees the `/IT/`, `/Hobbies/`, `/Civic/` target dirs for content).

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 4-01 | `/Shifting-Ground/` | `/IT/Shifting-Ground/` | Moves entire directory. |
| 4-02 | `/Recipes/` | `/Hobbies/Recipes/` | Move `/Recipes/` root-level directory into `/Hobbies/Recipes/`. **[VERIFY]** After this move the contents of the old `/Recipes/` live at `/Hobbies/Recipes/` — do not confuse with step 4-03. |
| 4-03 | `/Personal/Recipies/` | `/Hobbies/Recipes/` | Note: source name is misspelled ("Recipies"). **[VERIFY]** Both 4-02 and 4-03 merge into `/Hobbies/Recipes/`. Move contents individually if needed to avoid collision. Also check if `/Personal/Recipies/` overlaps with `/Personal/Recipts/` (handled in 3-B-12) — these appear to be different directories. |
| 4-04 | Loose files in `/Movies/` (Alan Watts, Bailey Wedding, Yoga, Tony Robbins files) | `/Media/Movies/` | **[VERIFY]** Do a PROPFIND on `/Movies/`. Identify loose files vs. subdirectories. Move each loose file individually. |
| 4-05 | `/Movies/Genna and David Home Videos from Childhood/` | `/Media/Home-Videos/` | **[VERIFY]** Confirm exact subdirectory name including spaces. Move the subdirectory itself (not its contents) so internal structure is preserved. |
| 4-06 | DELETE `/Movies/` (if empty after 4-04 and 4-05) | — | **[VERIFY]** Confirm empty before deleting. |
| 4-07 | `/Music/` | `/Media/Music/` | **[VERIFY]** If `/Music/` contains a nested `/Music/Music/` directory, flatten by moving the inner `/Music/Music/` contents up one level first, then moving the outer `/Music/` to `/Media/Music/`. Inspect structure before executing. |
| 4-08 | `/Photos/` | `/Media/Photos/` | Moves entire directory. |
| 4-09 | `/Books/` | `/Media/Books/` | **[VERIFY]** Before moving, inspect whether `/Books/` contains a Latvian-specific subdirectory (or if `/Latvian/Books/` is a separate path). See note below. |
| 4-10 | `/Latvian/Books/` subdir | **[VERIFY - DECISION REQUIRED]** | **[VERIFY]** Inspect contents of `/Latvian/Books/`. If Latvian-language learning books → keep in `/Latvian/Books/` (or move to `/Personal/Identity/Latvian-Citizenship/Books/`). If general e-books → move to `/Media/Books/`. This requires a content decision before executing. |

> Note on 4-10: The `/Latvian/` top-level directory is not in the "Do Not Touch" list but also not in the "Archive" or explicit move list. Treat it as needing a VERIFY decision before any operation.

---

## Phase 5 — Root Cleanup

Moves remaining loose files and the openclaw backup directory. Must run last because `/Inbox/` is created in Phase 1 and the openclaw backup has a Duplicati dependency.

| # | Source | Destination | Notes |
|---|--------|-------------|-------|
| 5-01 | `/openclaw-backup/` | `/Backup/openclaw/` | **[WARNING] Duplicati must be reconfigured FIRST.** Stop or reconfigure the Duplicati job that writes to this path before executing this move. After the move, update the Duplicati job's destination path to `/Backup/openclaw/`. Only then execute the MOVE. |
| 5-02 | Loose files at root: `Binder1.pdf`, EU Latvia docs, spreadsheets, `.md` files, PDFs | `/Inbox/` | **[VERIFY]** Do a full PROPFIND on the root. Identify ALL loose files (not directories). Move each individually. Do NOT move any directory listed in "Do Not Touch" or any directory not yet processed. |
| 5-03 | System/app files at root: `backends`, `history`, `idxstatus.txt`, `mimeview`, `ptrans` | `/Inbox/` | **[VERIFY]** Confirm these are actual files and not Nextcloud system artifacts that should not be moved. Moving Nextcloud-internal metadata files could break the instance. Cross-check with Nextcloud documentation or admin panel before moving any file whose purpose is unclear. |

---

## Do Not Touch — Confirmed Exclusions

These paths must not be moved, renamed, or deleted at any point during migration:

| Path | Reason |
|------|--------|
| `/joplin/` | Active note sync app |
| `/Zotero/` | Active reference manager |
| `/Documents/` | Preserved as-is |
| `/Shared/` | Shared folder — modifying could affect other users |
| `/Talk/` | Nextcloud Talk attachments |
| `/InstantUpload/` | Mobile auto-upload target |
| `/Notes/` (flat .md files only) | Only subdirectories moved in Phase 2; root .md files stay |
| `/Templates/` | Nextcloud templates |

---

## Additional Missing MKDIR Operations

The following target directories are referenced in Phase 3 but were not in the original Phase 1 MKDIR list. These MKDIRs must be added to Phase 1 (or executed immediately before the corresponding MOVE):

| Path | Required Before |
|------|----------------|
| `/Personal/Identity/Signature/` | 3-A-07 |
| `/Personal/Identity/wallet/` | 3-A-08 |
| `/Personal/Travel/` | 3-A-09 |
| `/Personal/Legal/Genna/` | 3-B-03 |
| `/Personal/Legal/Hibbs-Law/` | 3-B-15 |
| `/Personal/Theodore/` | 3-B-09 |
| `/Personal/School/` | 3-B-10 |

---

## Summary — Operation Counts

| Phase | MKDIRs | MOVEs | DELETEs | VERIFYs |
|-------|--------|-------|---------|---------|
| Phase 0 | 0 | 0 | 0 | 4 (manual checks) |
| Phase 1 | ~47 | 0 | 0 | 0 |
| Phase 2 | 0 | 17 | 0 | 12 |
| Phase 3 | 7 | ~35 | ~6 | ~30 |
| Phase 4 | 0 | ~10 | ~2 | ~10 |
| Phase 5 | 0 | ~2 + N files | 0 | 3 |
| **Total** | **~54** | **~65+** | **~8** | **~59** |

---

## Execution Checklist

Before starting:
- [ ] Duplicati job paused/reconfigured (for Phase 5-01)
- [ ] Desktop/mobile sync clients offline or paused
- [ ] Recent backup confirmed
- [ ] PROPFIND on root to confirm directory names match this plan

Per phase:
- [ ] Phase 1 all MKDIRs complete (including the 7 additions above)
- [ ] Phase 2 all archive moves complete, spot-check 2-3 destinations
- [ ] Phase 3-A complete (David Gutowsky/ children moved)
- [ ] Phase 3-B complete (other Personal/ subdirs moved)
- [ ] Phase 3-C/3-D complete (Civic/Hobbies/IT splits complete)
- [ ] Phase 4 complete (top-level dirs moved to Media/IT/Hobbies)
- [ ] Phase 5 complete (root cleanup, openclaw backup moved)

Post-migration:
- [ ] Update Duplicati job target to `/Backup/openclaw/`
- [ ] Re-enable desktop/mobile sync clients
- [ ] Spot-check 10-15 key file paths to confirm expected locations
- [ ] Update any bookmarks or app configs pointing to old paths
