# GitHub Pages deployment — SITE-0.3

The Building Energy Tools static website is deployed from the existing public repository through GitHub Actions.

## Production source

```text
Repository: dmitrievii/building-energy-tools
Branch:     main
Site root:  website/site/
```

Expected default GitHub Pages project URL:

```text
https://dmitrievii.github.io/building-energy-tools/
```

The Pages source in repository settings must be set to **GitHub Actions**.

## Deployment workflow

```text
.github/workflows/pages-deploy.yml
```

On an eligible push to `main`, the workflow:

1. checks out the exact main commit;
2. validates the static-site contract;
3. runs website regression tests;
4. configures GitHub Pages;
5. uploads only `website/site/` as the Pages artifact;
6. deploys that artifact through `actions/deploy-pages`.

The deployment job uses only the permissions required by GitHub Pages:

```text
contents: read
pages: write
id-token: write
```

No repository source files outside `website/site/` are published as website content.

## Release boundary

A successful deployment proves only that the static site is reachable on GitHub Pages. It does not by itself close the Building Energy Tools publication/legal/privacy gate.

After the first successful deployment, SITE-0.3 requires a live-host audit of the production URL for:

- HTTP and route availability;
- desktop/tablet/mobile rendering;
- external network requests;
- browser console/page errors;
- accessibility regression;
- actual GitHub Pages hosting behavior.

Until that live audit is completed, the repository publication status remains fail-closed.
