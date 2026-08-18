document.addEventListener("DOMContentLoaded", function () {
  var courseSelect = document.getElementById("id_course");
  var feeInput = document.getElementById("id_monthly_fee");
  if (!courseSelect || !feeInput) return;
  var raw = courseSelect.getAttribute("data-fee-choices") || "";
  var map = {};
  raw.split(",").forEach(function (pair) {
    var parts = pair.split(":");
    if (parts.length === 2) map[parts[0]] = parts[1];
  });
  courseSelect.addEventListener("change", function () {
    var fee = map[courseSelect.value];
    if (fee !== undefined && !feeInput.value) {
      feeInput.value = fee;
    }
  });
});
