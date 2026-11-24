// Matches backend/valuation.py. Dollar-per-unit assumptions are ANNUAL.
export function operatingEstimate(p, a) {
  if (!p.is_rental || !p.value || !p.rent) return null;
  const units=p.expense_unit_count;
  if ((a.maintenance_mode==='per_unit'||a.insurance_mode==='per_unit') && (!Number.isInteger(units)||units<1)) return null;
  const value=p.value.estimate, annual=p.rent.estimate*12;
  const taxes=a.annual_taxes ?? p.details.annual_taxes ?? value*a.fallback_tax_rate;
  const maintenance=a.maintenance_mode==='per_unit'?units*a.maintenance_per_unit:annual*a.maintenance;
  const insurance=a.insurance_mode==='per_unit'?units*a.insurance_per_unit:a.insurance_mode==='percent_rent'?annual*a.insurance_rent_rate:value*a.insurance_rate;
  const noi=annual*(1-a.vacancy-a.management)-taxes-maintenance-insurance;
  return {noi,cap:noi/value};
}
