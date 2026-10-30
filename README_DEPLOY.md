# ABP Report Builder — Android Cloud Deployment Package

This package is **prepared for deployment, not already hosted**. It keeps 37 ABP master Excel templates, excludes six historical project workbooks to avoid uploading past client data, and provides a touch-friendly browser UI. The existing engineering limitations still apply.

## Easiest hosted setup (Render.com)

1. Create a **private GitHub repository** and upload the files in this folder (keep the folder structure). **Do not make the repo public**: ABP templates and code are proprietary.
2. Sign in to Render.com and choose **New > Blueprint**, connect the private repository, and approve the `render.yaml` configuration. Alternatively choose New > Web Service > Connect repo > Docker.
3. Choose a paid instance with sufficient memory for your PDFs; `render.yaml` requests the Starter plan (check current provider pricing).
4. When prompted for `ABP_ACCESS_PASSWORD`, enter a long unique password (at least 12 characters; ideally 20+). Do not put the password in GitHub or chat.
5. Deploy. Render supplies an HTTPS URL like `https://abp-tab-report-builder.onrender.com` (actual URL may differ). Open the real URL in Android Chrome. Username is `abp`; password is what you configured.
6. In Chrome's menu choose **Add to Home screen** (or **Install app** if offered).

## What works
- Upload text-based PDF, XLSX, CSV schedules; review extracted tags and *unverified* numeric suggestions.
- Manually verify values, choose from 37 original ABP templates, download draft Excel reports.
- Save project review as JSON and restore it later. **Keep the JSON in company-approved secure storage.**

## Security and operational limits
- HTTPS is provided by the hosting platform. Do not publish this app without HTTPS.
- One shared HTTP Basic login, not individual technician accounts, MFA, audit trail, or role-based access. **Not yet approved for sensitive customer drawings or production deployment.**
- Browser/project review JSON is downloaded to your device; the server does not persist uploads or projects. Files are temporarily processed in RAM. Do not rely on the host to back up project work.
- No scanning of image-only PDFs, incomplete schedule and diffuser mapping, no certification/signoff.
- Hosting incurs third-party charges and may involve transmitting drawings to the hosting provider; obtain ABP/customer authorization first.
- Keep hosting dashboard and repository access restricted. Change password after staff departures.
- For field use at scale, add company SSO, separate users, project database, encrypted storage, audit logs, rate limiting, secure backups, and an engineering acceptance test.

## Local developer test
`python -m pip install -r requirements.txt`
`ABP_ACCESS_PASSWORD='choose-your-own-strong-password' python abp_server.py 8765 --lan`
Do not expose local HTTP directly to the public internet.
