# Implementation Plan - Add Description to Gift Card Packages

The user wants to add a "Description" field to Gift Card Packages. This description allows for more attractive marketing copy (e.g. "Relax and unwind...") separate from the technical list of services.

## User Review Required
> [!NOTE]
> This change adds a `description` column (TEXT) to the `packages` table.
> I have not been able to locate the "public landing page" code (`barberia.jvcorp.pe`) in this workspace, so this plan only covers the **Admin** side (Database + Management Interface). You may need to update the public website code separately to display this new description.

## Proposed Changes

### Database
#### [NEW] [Migration Script]
- Create `add_package_description.py` to add `description TEXT` column to `packages` table.

### Backend
#### [MODIFY] [routes_marketing.py](file:///d:/JV_Studio/jv_studio_app/app/routes_marketing.py)
- Update `nuevo_paquete` (POST): Accept `description` form field and insert into DB.
- Update `editar_paquete` (POST): Accept `description` form field and update DB.

### Frontend
#### [MODIFY] [crear_paquete.html](file:///d:/JV_Studio/jv_studio_app/app/templates/marketing/crear_paquete.html)
- Add a `<textarea>` for `description` in the form.
- Pre-fill it when editing.

## Verification Plan

### Manual Verification
1.  **Create Package**:
    - Go to `/marketing/paquetes/nuevo`.
    - Enter Name, Price, Services.
    - Enter a Description: "Disfruta de una experiencia única...".
    - Save.
    - Verify redirection to list.
2.  **Edit Package**:
    - Click "Edit" on the new package.
    - Verify Description is pre-filled.
    - Change Description.
    - Save.
    - Verify update is persisted (re-open edit).
