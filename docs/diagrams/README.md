# Regenerating the ARCHITECTURE.md diagrams

Edit `ARCHITECTURE.template.md` (prose) or `gen_diagrams.py` (box diagrams), then from the repo root:

```powershell
python docs/diagrams/gen_diagrams.py docs/diagrams/ARCHITECTURE.template.md ARCHITECTURE.md
```
