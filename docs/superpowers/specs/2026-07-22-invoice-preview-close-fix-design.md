# Invoice Preview Close Fix Design 
 
## Problem 
 
The expense page mounts two InvoicePreviewDrawer instances. The component defaults open to true and renders from open alone. Clearing the invoice on close therefore leaves both drawers visible. 
 
## Approved Design 
 
- Default the drawer open prop to false. 
- Render only when open is true and an invoice name exists. 
- Pass explicit open state from both parent call sites using Boolean of the selected invoice. 
- Keep the existing close event so the parent clears its selected invoice. 
- Add a regression contract test and verify the live dialog count changes from one to zero after clicking Close. 
 
## Constraints 
 
- Do not change invoice files, OCR records, reimbursement records, or permissions. 
- Do not merge into main. 
- Rebuild and deploy only the frontend assets.
