-- The following SQL queries can be used to import data from the database to Azure ML by using a Azure ML data asset. 

select pa.id paragraph_id, item_of_business, po.person_id, po.first_name, po.last_name, po.council, po.party, pa.in_admin_role, pa.text, s.date, s.title session_title, s.id session_id
from "PARAGRAPH" pa
left join "POLITICIAN" po on pa.speaker_entry_id = po.id
inner join "SESSION" s on pa.session_id = s.id
order by s.date ASC, pa.id ASC;


select person_id, ts_id, first_name, last_name, council, party, valid_from, valid_to from "POLITICIAN";