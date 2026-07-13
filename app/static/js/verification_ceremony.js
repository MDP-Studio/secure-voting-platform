(function () {
  "use strict";

  const form = document.getElementById("ceremony-form");
  const progress = document.getElementById("ceremony-progress");
  const status = document.getElementById("ceremony-status");
  const completion = document.getElementById("ceremony-complete");

  if (!form || !progress || !status || !completion) {
    return;
  }

  const checks = Array.from(form.querySelectorAll("[data-ceremony-check]"));
  const firstCheck = checks[0];

  function updateCeremonyState() {
    const completed = checks.filter((check) => check.checked).length;
    const total = checks.length;

    progress.max = total;
    progress.value = completed;
    completion.hidden = completed !== total;

    if (completed === total) {
      status.textContent =
        "6 of 6 rehearsal checks marked complete. No real election has been verified.";
      return;
    }

    status.textContent = `${completed} of ${total} rehearsal checks marked complete.`;
  }

  form.addEventListener("change", updateCeremonyState);
  form.addEventListener("reset", function () {
    window.setTimeout(function () {
      updateCeremonyState();
      if (firstCheck) {
        firstCheck.focus();
      }
    }, 0);
  });

  updateCeremonyState();
})();
