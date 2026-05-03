-- Update table to include DOB
ALTER TABLE staff_master ADD COLUMN dob DATE;

-- Refresh the Monthly Summary View for the new field
CREATE OR REPLACE VIEW monthly_payroll_summary AS
SELECT 
    sm.id, sm.name, sm.father_name, sm.dob, sm.department, 
    sm.account_no, sm.ifsc, sm.daily_wage,
    COUNT(att.id) FILTER (WHERE att.status = 'Present') as days_present,
    COUNT(att.id) FILTER (WHERE att.status = 'Half-Day') as half_days,
    COALESCE(SUM(adv.amount), 0) as total_advances,
    ((COUNT(att.id) FILTER (WHERE att.status = 'Present') * sm.daily_wage) + 
     (COUNT(att.id) FILTER (WHERE att.status = 'Half-Day') * (sm.daily_wage / 2)) - 
     COALESCE(SUM(adv.amount), 0)) as net_payable
FROM staff_master sm
LEFT JOIN attendance att ON sm.id = att.staff_id AND DATE_TRUNC('month', att.date) = DATE_TRUNC('month', CURRENT_DATE)
LEFT JOIN advances adv ON sm.id = adv.staff_id AND DATE_TRUNC('month', adv.date) = DATE_TRUNC('month', CURRENT_DATE)
GROUP BY sm.id, sm.name, sm.father_name, sm.dob, sm.daily_wage, sm.account_no, sm.ifsc, sm.department;
