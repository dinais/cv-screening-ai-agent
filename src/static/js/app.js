document.addEventListener("DOMContentLoaded", () => {
  const flashes = document.querySelectorAll(".flash");
  flashes.forEach((node) => {
    window.setTimeout(() => {
      node.style.opacity = "0";
      node.style.transition = "opacity 250ms ease";
    }, 4000);
  });
});
