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
      if (event.target.closest("a, button, summary, details, dialog")) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      window.location.href = row.dataset.href;
    });
  });

  const setPanelOpen = (panelId, open) => {
    const panel = document.getElementById(panelId);
    if (!panel) {
      return;
    }
    panel.hidden = !open;
    document.querySelectorAll(`[data-toggle-panel="${CSS.escape(panelId)}"]`).forEach((button) => {
      button.setAttribute("aria-expanded", open ? "true" : "false");
      if (!button.classList.contains("row-toggle")) {
        button.textContent = open ? "Hide" : "View";
      }
    });
  };

  document.querySelectorAll("[data-toggle-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      const panelId = button.dataset.togglePanel;
      const panel = document.getElementById(panelId);
      if (!panel) {
        return;
      }
      const willOpen = panel.hidden;
      const group = button.dataset.toggleGroup;
      if (willOpen && group) {
        document.querySelectorAll(`[data-toggle-group="${CSS.escape(group)}"]`).forEach((other) => {
          if (other.dataset.togglePanel !== panelId) {
            setPanelOpen(other.dataset.togglePanel, false);
          }
        });
      }
      setPanelOpen(panelId, willOpen);
    });
  });

  document.querySelectorAll("[data-open-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = button.closest("dialog");
      if (dialog && typeof dialog.close === "function") {
        dialog.close();
      }
      const toggle = document.querySelector(
        `.button[data-toggle-panel="${CSS.escape(button.dataset.openPanel)}"]`
      );
      if (toggle && toggle.getAttribute("aria-expanded") !== "true") {
        toggle.click();
      }
    });
  });

  const openDialog = (dialog) => {
    if (!dialog || typeof dialog.showModal !== "function" || dialog.open) {
      return;
    }
    dialog.showModal();
    const field = dialog.querySelector("input, textarea");
    if (field) {
      field.focus();
    }
  };

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      openDialog(document.getElementById(button.dataset.openDialog));
    });
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
    if (dialog.hasAttribute("data-open-on-load")) {
      openDialog(dialog);
    }
  });
});
