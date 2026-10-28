"""Strict activity CSV parser tests; no external account or database required."""
import unittest
from activity_import import parse_activity_csv, corrected_activity_rows

ZONE = 'Europe/Moscow'


def read(text, filename='activities.csv', mime='text/csv'):
    return parse_activity_csv(text.encode('utf-8'),filename,mime,ZONE)


class ActivityImportTests(unittest.TestCase):
    def test_preview_is_normalized_and_source_fingerprint_stable(self):
        content='date;activity;minutes;kcal\n2025-10-25;Эллипс;25;240\n'
        one=read(content)
        two=read('date,activity,minutes,kcal\n2025-10-25,Эллипс,25,240\n')
        self.assertEqual(len(one),1)
        self.assertEqual(one[0]['fingerprint'],two[0]['fingerprint'])
        self.assertEqual(one[0]['performed_at'].isoformat(),'2025-10-25T09:00:00+00:00')
        self.assertEqual(one[0]['kcal'],240)
        self.assertEqual(one[0]['minutes'],25)

    def test_user_corrections_validate_and_change_dedupe_key(self):
        original=read('date,activity,minutes,kcal\n2025-10-25,Ходьба,20,75\n')
        changes=[{'date':'2025-10-25','activity':'Бег',
                  'minutes':'22','kcal':'88'}]
        fixed=corrected_activity_rows(original,changes,ZONE)
        self.assertNotEqual(fixed[0]['fingerprint'],original[0]['fingerprint'])
        self.assertEqual(fixed[0]['minutes'],22)
        self.assertEqual(fixed[0]['kcal'],88)
        for bad in ([{'date':'2025-10-25','activity':'Бег',
                      'minutes':True,'kcal':88}],
                    [{'date':'2025-10-25','activity':'Бег',
                      'minutes':22,'kcal':88,'extra':'x'}],[], 'string'):
            with self.assertRaises(ValueError):
                corrected_activity_rows(original,bad,ZONE)

    def test_reject_unsafe_or_ambiguous_files(self):
        good='date,activity,minutes,kcal\n2025-10-25,Ходьба,20,80\n'
        for text in (
            'date,activity,minutes,kcal\n2025-10-25,Ходьба,20,80.5\n',
            'date,activity,minutes,kcal\n2025-10-25,Ходьба,20,-10\n',
            'date,activity,minutes,kcal\n2025-10-25,=1+1,20,80\n',
            'date,activity,minutes,kcal\n2025-10-25,Ходьба,0,80\n',
            'date,activity,minutes,kcal\n2025-10-25,Ходьба,20,6000\n',
            'date,activity,minutes,kcal\n2025-02-30,Ходьба,20,80\n',
            'date,activity,minutes,kcal\n2099-10-25,Ходьба,20,80\n',
            'date,activity,minutes,active_calories\n2025-10-25,Ходьба,20,80\n',
            'date,activity,minutes,kcal,extra\n2025-10-25,Ходьба,20,80,2\n',
            'date,activity,minutes,kcal\n2025-10-25,Ходьба,20\n',
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    read(text)
        with self.assertRaises(ValueError):
            parse_activity_csv(b'PK\x03\x04' +good.encode(),'report.csv','text/csv',ZONE)
        with self.assertRaises(ValueError):
            parse_activity_csv(good.encode(),'report.xlsx','text/csv',ZONE)
        with self.assertRaises(ValueError):
            parse_activity_csv(good.encode(),'report.csv','application/pdf',ZONE)
        with self.assertRaises(ValueError):
            parse_activity_csv(good.encode()*10000,'report.csv','text/csv',ZONE)
        with self.assertRaises(ValueError):
            read('date,activity,minutes,kcal\n'+'2025-10-25,Ходьба,20,80\n'*31)
        self.assertEqual(len(read(good)),1)


if __name__ == '__main__':
    unittest.main()
