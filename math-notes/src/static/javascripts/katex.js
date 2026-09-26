// Renders math after every page load, including Material's instant-navigation page
// swaps (document$ is Material's own navigation observable, not a typo of `document`) --
// without subscribing to that instead of a plain DOMContentLoaded listener, math on any
// page reached via instant navigation (the default, see mkdocs.yml's navigation.instant)
// would never get rendered after the first page load.
document$.subscribe(({ body }) => {
  renderMathInElement(body, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
      { left: "\\[", right: "\\]", display: true },
    ],
  });
});
