# Eval corpus

Public policy documents used to test PolicyPilot. Each has a different writing style,
so retrieval and answering are tested on more than one kind of document.

| File | Type | Source |
|---|---|---|
| `uol_student_handbook_2025.pdf` | University student handbook | (already uploaded, document 31) |
| `faversham_tc_employee_handbook_2024.pdf` | UK town council employee handbook (HR) | https://favershamtowncouncil.gov.uk/wp-content/uploads/2024/09/Faversham-Town-Council-Handbook-2024-Updated.pdf |
| `east_dunbartonshire_ict_acceptable_use_policy.pdf` | Scottish council ICT acceptable-use policy (staff, public, schools) | https://www.eastdunbarton.gov.uk/media/m2bosl2o/acceptable-use-of-ict-facilities-policy.pdf |

Download them on your machine (PowerShell, from the project folder):

    powershell -ExecutionPolicy Bypass -File corpus/download.ps1

Then upload each through `POST /api/v1/documents` (Swagger) so they are chunked and embedded.

The Jisc Janet acceptable-use policy was the first choice for the IT document, but its site blocks scripted downloads (Cloudflare bot check), so it was swapped for this one.
