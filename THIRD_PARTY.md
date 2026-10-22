# Third-party components bundled in `aaryaai_finance/web`

| Component | Version | Licence | Use |
|---|---|---|---|
| [Chart.js](https://www.chartjs.org/) | 4.4.4 | MIT | charts |
| [marked](https://marked.js.org/) | 12.0.2 | MIT | rendering assistant replies |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.16 | Apache-2.0 / MPL-2.0 | sanitising rendered HTML |
| [Barlow, Barlow Condensed](https://fonts.google.com/specimen/Barlow) | — | SIL Open Font License 1.1 | UI font |
| [IBM Plex Mono](https://github.com/IBM/plex) | — | SIL Open Font License 1.1 | numbers |

They are vendored so the app works fully offline. To update one, download the release's package from the npm registry, check the download against the registry's `integrity` hash, copy the file into `web/vendor/`, change the version here, and run `pytest -m ui`. The aaryaai name and logo in `web/brand/` belong to aaryaai; forks should replace them with their own.
