# Acme Bank Importer Example Directory

This directory contains regression test artifacts for an "Acme Bank" PDF importer.

## Purpose

The files demonstrate the expected outputs from the ingestion process for a hypothetical `acmebank1.pdf` file (which is not included in this directory). These files are typically used to verify:

1.  **Accounting entries (`.extract`):** The expected Beancount directives returned by the importer and rendered as text.
2.  **Account Identification (`.file_account`):** The specific Beancount account name that the importer should identify for the given file.

## Files

-   `acmebank1.pdf.extract`:
    -   Contains the expected rendered Beancount directives for `acmebank1.pdf`.
    -   Used by the version 2 ingestion regression harness to check the importer's accounting output. Raw PDF text is a separate intermediate result.
    -   *Note: Currently empty in this example.*

-   `acmebank1.pdf.file_account`:
    -   Contains the expected account name: `Assets:US:AcmeBank`.
    -   Used to verify that the importer correctly maps the filename or content to the appropriate Beancount account.

## Context

This structure follows typical patterns for Beancount ingestion regression testing, where input files (`.pdf`, `.csv`) are processed, and their rendered accounting entries (`.extract`) and account identification (`.file_account`) are compared against known good values.
