document.addEventListener("DOMContentLoaded", () => {
  const flashes = document.querySelectorAll(".flash");
  flashes.forEach((node) => {
    window.setTimeout(() => {
      node.style.opacity = "0";
      node.style.transition = "opacity 250ms ease";
    }, 4000);
  });

  document.querySelectorAll("tr.row-link[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, summary, details")) {
        return;
      }
      window.location.href = row.dataset.href;
    });
  });
});
