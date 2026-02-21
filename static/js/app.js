/* UdharFree — Dynamic split form logic */

(function () {
  'use strict';

  // Only run on the add-expense page
  if (!document.getElementById('expense-form')) return;

  const memberCheckboxes = document.querySelectorAll('input[name="members"]');
  const splitRadios      = document.querySelectorAll('input[name="split_type"]');
  const pctInputsDiv     = document.getElementById('pct-inputs');
  const exactInputsDiv   = document.getElementById('exact-inputs');
  const pctFields        = document.getElementById('pct-fields');
  const exactFields      = document.getElementById('exact-fields');
  const pctTotalDisplay  = document.getElementById('pct-total-display');
  const exactTotalDisplay = document.getElementById('exact-total-display');
  const totalAmountInput = document.getElementById('total_amount');

  // ---- Helpers ----

  function getCheckedMembers() {
    return Array.from(memberCheckboxes)
      .filter(cb => cb.checked)
      .map(cb => ({ username: cb.dataset.username, display: cb.dataset.display }));
  }

  function getSplitType() {
    const checked = document.querySelector('input[name="split_type"]:checked');
    return checked ? checked.value : 'equal';
  }

  function getTotalAmount() {
    return parseFloat(totalAmountInput.value) || 0;
  }

  // ---- Render split input fields ----

  function renderPctFields(members) {
    pctFields.innerHTML = '';
    const equal = members.length > 0 ? (100 / members.length) : 0;
    members.forEach(m => {
      const div = document.createElement('div');
      div.className = 'split-field';
      div.innerHTML = `
        <label>${m.display}</label>
        <input type="number" name="pct_${m.username}" min="0" max="100" step="0.01"
               value="${equal.toFixed(2)}" placeholder="0" class="pct-input" />
        <span style="font-size:.875rem;color:var(--gray-400)">%</span>
      `;
      pctFields.appendChild(div);
    });
    updatePctTotal();
  }

  function renderExactFields(members) {
    exactFields.innerHTML = '';
    const total = getTotalAmount();
    const perPerson = members.length > 0 ? (total / members.length) : 0;
    members.forEach(m => {
      const div = document.createElement('div');
      div.className = 'split-field';
      div.innerHTML = `
        <label>${m.display}</label>
        <span style="font-size:.875rem;color:var(--gray-600)">₹</span>
        <input type="number" name="exact_${m.username}" min="0" step="0.01"
               value="${perPerson.toFixed(2)}" placeholder="0.00" class="exact-input" />
      `;
      exactFields.appendChild(div);
    });
    updateExactTotal();
  }

  // ---- Update running totals ----

  function updatePctTotal() {
    const inputs = pctFields.querySelectorAll('.pct-input');
    let sum = 0;
    inputs.forEach(i => { sum += parseFloat(i.value) || 0; });
    const rounded = Math.round(sum * 100) / 100;
    pctTotalDisplay.textContent = `Total: ${rounded}%`;
    pctTotalDisplay.style.color = Math.abs(rounded - 100) < 0.02 ? 'var(--green)' : 'var(--red)';
  }

  function updateExactTotal() {
    const inputs = exactFields.querySelectorAll('.exact-input');
    let sum = 0;
    inputs.forEach(i => { sum += parseFloat(i.value) || 0; });
    const total = getTotalAmount();
    exactTotalDisplay.textContent = `Total: ₹${sum.toFixed(2)} / ₹${total.toFixed(2)}`;
    exactTotalDisplay.style.color = Math.abs(sum - total) < 0.02 ? 'var(--green)' : 'var(--red)';
  }

  // ---- Toggle split sections ----

  function refreshSplitUI() {
    const type = getSplitType();
    const members = getCheckedMembers();

    pctInputsDiv.classList.add('hidden');
    exactInputsDiv.classList.add('hidden');

    if (type === 'percentage') {
      pctInputsDiv.classList.remove('hidden');
      renderPctFields(members);
    } else if (type === 'exact') {
      exactInputsDiv.classList.remove('hidden');
      renderExactFields(members);
    }
  }

  // ---- Event listeners ----

  memberCheckboxes.forEach(cb => cb.addEventListener('change', refreshSplitUI));
  splitRadios.forEach(r => r.addEventListener('change', refreshSplitUI));
  totalAmountInput.addEventListener('input', function () {
    const type = getSplitType();
    if (type === 'exact') {
      const members = getCheckedMembers();
      renderExactFields(members);
    }
    updateExactTotal();
  });

  // Delegate live-update events on dynamically created inputs
  pctFields.addEventListener('input', updatePctTotal);
  exactFields.addEventListener('input', updateExactTotal);

  // ---- Auto-fill equal percentages button ----
  // We add a small helper link to reset percentages
  pctInputsDiv.querySelector('.split-input-header').insertAdjacentHTML('beforeend',
    '<button type="button" id="auto-pct-btn" style="font-size:.75rem;color:var(--primary);background:none;border:none;cursor:pointer;font-weight:600;margin-left:.5rem;">Auto-fill equal</button>'
  );

  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'auto-pct-btn') {
      const members = getCheckedMembers();
      if (!members.length) return;
      const equal = (100 / members.length).toFixed(2);
      pctFields.querySelectorAll('.pct-input').forEach(i => { i.value = equal; });
      updatePctTotal();
    }
  });

  // ---- Initial render ----
  refreshSplitUI();

})();
