# Mfg Item Viewer: 3DEXPERIENCE 3DDashboard widget

Search a Manufacturing Item by title, name or physical ID (or drop one from MFN or search), then see:

- its details (collapsible);
- its full multi-level BOM;
- for every row:
  - the **Specification** files (documents attached with a *Specification Document* link), as links that open the file;
  - the **Manufacturer Equivalent Item**, manufacturer, manufacturer part number and Equivalent Qualification.

**Export PDF** downloads what is shown, with a DRAFT watermark on every page. It also attaches an appendix holding the contents of every specification file:

- PDF files keep their pages;
- Word files are re-laid out as text pages;
- each Excel sheet becomes a table.

The widget is read-only and works with the signed-in user's session.

## Add it to a dashboard
Use either of these options:
- **URL** (preferred, updates automatically): in "Run Your App", enter
  `https://joseph-aj-1.github.io/Experiments/mfgitem-viewer/index.html`.
  If the URL is refused, a platform administrator has to allow it.
- **Upload**: upload `index.html` as the app file. It is only a small loader that pulls everything else from GitHub Pages, so later changes still arrive without uploading again.

## How it is put together
```
mfgitem-viewer/
├── index.html            widget page: metadata + a small loader (reads manifest.json)
├── manifest.json         version + the CSS/JS files to load, in order
├── css/mfgitem-viewer.css
├── js/
│   ├── core.js           namespace (window.MFV), helpers, WAFData requests, security context
│   ├── ui.js             layout, collapsible details
│   ├── bom.js            search, item details, multi-level BOM table      (dsmfg)
│   ├── mei.js            MEI columns via Equivalent Qualifications          (dssrc, Sourcing)
│   ├── specs.js          Specification column, open file via FCS ticket     (Document Web Services)
│   ├── libs.js           loads jsPDF / pdf-lib / mammoth / SheetJS on first use
│   ├── pdf-report.js     main PDF pages: table, appendix list, footer, DRAFT watermark
│   ├── pdf-appendix.js   spec files to PDF pages, merge, page headers, links
│   ├── export.js         the Export PDF flow
│   └── main.js           MFV.start(): platform modules, services, events
├── vendor/               third-party libraries (+ licenses/); public CDNs are the backup
└── test/                 offline tests with a mocked 3DDashboard
```
`index.html` downloads `manifest.json` without caching, then loads each file with `?v=<version>`.
After a change, **bump `version` in manifest.json** so browsers fetch the new files right away. (GitHub Pages caches files for about 10 minutes otherwise.)

To add a module, create `js/<name>.js` in the same `(function (M) { ... })(window.MFV);` form and list it in `manifest.json` before `main.js`.

## APIs used
| Purpose | Call |
| --- | --- |
| Security context | `GET {3DSpace}/resources/modeler/pno/person?current=true&select=collabspaces&select=preferredcredentials` |
| Search | `GET {3DSpace}/resources/v1/modeler/dsmfg/dsmfg:MfgItem/search?$searchStr=…&$top=25` |
| Item | `GET {3DSpace}/resources/v1/modeler/dsmfg/dsmfg:MfgItem/{id}?$mask=dsmfg:MfgItemMask.Details` |
| BOM | `GET {3DSpace}/resources/v1/modeler/dsmfg/dsmfg:MfgItem/{id}/dsmfg:MfgItemInstance?$mask=dsmfg:MfgItemInstanceMask.Details` |
| Qualifications | `POST {Sourcing}/resources/v1/modeler/dssrc/qualifications/contextLocate?type=equivalentQualification` (CSRF from {Sourcing}) |
| MEI | `GET {3DSpace}/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/{id}` (+ search, Details mask), `GET …/dseng/dseng:EngItem/{id}` |
| Specifications | `GET {3DSpace}/resources/v1/modeler/documents/parentId/{id}?parentRelName=SpecificationDocument&include=files` |
| File download | `PUT {3DSpace}/resources/v1/modeler/documents/{docId}/files/{fileId}/DownloadTicket` (CSRF from {3DSpace}), giving an FCS URL |

{3DSpace} and {Sourcing} come from i3DXCompassServices; every call adds `?tenant=<platform id>` and the `SecurityContext` header.

## PDF appendix rules
Each file appears once, in BOM order, labelled A1, A2, … and listing every item it is attached to.

Included:
- PDF;
- .docx (headings, paragraphs, lists, tables, PNG/JPEG images);
- .xlsx, .xlsm, .xls and .csv (up to 2,000 rows and 40 columns per sheet).

Listed with the reason, but not included:
- old .doc files;
- other file types;
- files over 30 MB;
- files you can't download, and downloads that fail.

The file server is tried directly first, then through `WAFData.proxifiedRequest`.

## Tests
```
pip install playwright pypdf
python3 test/run_test.py
```
The tests replay real responses through a mocked dashboard (widget, require, WAFData, compass, drag & drop). GitHub Pages is served from this folder. There are 71 checks:
- loader and manifest order;
- multi-level BOM, MEI and Specification columns;
- opening a spec;
- PDF content, watermark, paging, appendix from PDF/Word/Excel, links;
- proxy and offline fallbacks;
- scrolling.

## Notes from deployment
- **Size limit:** the 3DDashboard refuses uploaded app files above roughly 50 KB, which is why the app is now split into files.
- **Re-minified scripts:** the dashboard re-minifies inline scripts in uploaded files, and its renamer confuses a `catch` variable with an outer variable of the same name. The inline loader in `index.html` is kept minimal for that reason. The files in js/ are loaded as-is.
