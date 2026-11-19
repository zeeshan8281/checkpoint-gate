// Keep URLs shared before the site split working.
const params = new URLSearchParams(location.search);
if (params.has("task") || params.has("condition") || location.hash === "#traces") {
  location.replace(`/explorer/${location.search}`);
} else if (location.hash === "#method") {
  location.replace("/method/");
}
