# Security policy

Thanks Mom deletes and moves files, so two kinds of problems count as security issues here:

- **Data loss:** a file was removed or changed and `mom.py undo .` could not bring it back.
- **Classic vulnerabilities:** for example, a crafted file name or plan that makes `apply` touch something outside the project folder, or that runs a command.

## Reporting

Please report these **privately**: open the repository's **Security** tab and choose **Report a vulnerability**. Don't use a public issue for them.

Include:
- `mom.py --version`, your OS and Python version
- what was lost or what could be triggered, and the steps to reproduce it
- the scan summary, and `.mom/archive-*.json` if there is one. Remove anything private first.

You'll get a reply within a week. Confirmed data-loss bugs get a fix in a patch release, and a note in the CHANGELOG.

A file being boxed up or asked about when it shouldn't have been is not a security issue, because `undo` restores it. Please use the **"Wrong decision"** issue form for that.

## Supported versions

Only the latest minor release gets fixes (currently **1.2.x**).
