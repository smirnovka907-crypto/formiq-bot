"""Telegram profile read-back regressions; offline, never call production API."""
import importlib
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hashlib
from PIL import Image


class TelegramBrandingVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_branding',
            'DATABASE_URL': 'postgresql://unused:unused@example.invalid/never_connect',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.m = importlib.import_module('main')

    def test_approved_art_is_same_bytes_as_welcome_art(self):
        from approved_assets import WELCOME_JPEG, AVATAR_JPEG
        from welcome_art import welcome_jpeg, avatar_jpeg
        self.assertEqual(welcome_jpeg(), WELCOME_JPEG)
        self.assertEqual(avatar_jpeg(), AVATAR_JPEG)
        from approved_assets import AVATAR_PNG, WELCOME_PNG
        self.assertEqual(WELCOME_JPEG, WELCOME_PNG)
        self.assertEqual(hashlib.sha256(AVATAR_PNG).hexdigest(),
                         '690c038a70c18250c0c4e68775dd7419b13078a0a66177b66b59d04c133ca9dd')
        self.assertEqual(hashlib.sha256(WELCOME_PNG).hexdigest(),
                         '8a485bae6e08b0027a8a9f30a9a578e9990ddceabd0d626e6ba082fa184d9bae')
        for artwork, format_name in ((AVATAR_PNG,'PNG'),(WELCOME_PNG,'PNG'),
                                      (AVATAR_JPEG,'JPEG')):
            with Image.open(io.BytesIO(artwork)) as pic:
                self.assertEqual(pic.format, format_name)
                self.assertGreaterEqual(min(pic.size), 200)
        self.assertLess(len(self.m.FORMIQ_BOT_ABOUT), 121)
        self.assertLess(len(self.m.FORMIQ_BOT_DESCRIPTION), 513)

    def test_live_bot_avatar_uses_official_photo_read_back(self):
        m=self.m
        with patch.object(m.BOT, 'get_me', return_value=SimpleNamespace(id=123)) as me, \
             patch.object(m.BOT, 'get_user_profile_photos',return_value=SimpleNamespace(
                 photos=[[SimpleNamespace(file_id='PHOTO_ID')]])) as photos, \
             patch.object(m.BOT, 'get_file',return_value=SimpleNamespace(
                 file_path='photos/current.jpg')) as f, \
             patch.object(m.BOT,'download_file',return_value=b'CURRENT') as dl:
            self.assertEqual(m._telegram_current_avatar_bytes(),b'CURRENT')
        me.assert_called_once()
        photos.assert_called_once_with(123,limit=1)
        f.assert_called_once_with('PHOTO_ID')
        dl.assert_called_once_with('photos/current.jpg')

    def test_matching_avatar_is_not_uploaded_again(self):
        from welcome_art import avatar_jpeg
        m=self.m
        with patch.object(m,'db',side_effect=AssertionError('No database access')), \
             patch.object(m,'_telegram_current_avatar_bytes',
                          return_value=avatar_jpeg()) as current, \
             patch.object(m.urllib.request,'urlopen') as upload:
            m.apply_approved_avatar_once()
        current.assert_called_once()
        upload.assert_not_called()

    def test_missing_avatar_uploads_and_confirms_from_telegram(self):
        from welcome_art import avatar_jpeg
        m=self.m
        with patch.object(m,'db',side_effect=AssertionError('No database access')), \
             patch.object(m,'_telegram_current_avatar_bytes',
                          side_effect=[None,avatar_jpeg()]) as current, \
             patch.object(m.urllib.request,'urlopen') as upload:
            upload.return_value.__enter__.return_value.read.return_value=b'{"ok":true,"result":true}'
            m.apply_approved_avatar_once()
            request=upload.call_args.args[0]
            self.assertIn(b'attach://avatar',request.data)
            self.assertIn(avatar_jpeg(),request.data)
        self.assertEqual(current.call_count,2)
        upload.assert_called_once()

    def test_different_photo_is_corrected_but_read_errors_do_not_upload(self):
        from welcome_art import avatar_jpeg
        m=self.m
        different=io.BytesIO()
        Image.new('RGB',(512,512),(12,23,200)).save(different,format='JPEG')
        self.assertFalse(m._avatar_looks_like_approved(different.getvalue(),avatar_jpeg()))
        with patch.object(m,'_telegram_current_avatar_bytes',
                          side_effect=[different.getvalue(),avatar_jpeg()]), \
             patch.object(m.urllib.request,'urlopen') as upload:
            upload.return_value.__enter__.return_value.read.return_value=b'{"ok":true}'
            m.apply_approved_avatar_once()
        upload.assert_called_once()
        with patch.object(m,'_telegram_current_avatar_bytes',
                          side_effect=RuntimeError('API unavailable')), \
             patch.object(m.urllib.request,'urlopen') as upload:
            with self.assertRaisesRegex(RuntimeError,'inspection failed'):
                m.apply_approved_avatar_once()
        upload.assert_not_called()

    def test_about_description_checked_in_both_telegram_locales(self):
        m=self.m
        state={loc:{'about':'OLD','desc':'OLD'} for loc in (None,'ru')}
        get_about=lambda language_code=None:SimpleNamespace(
            short_description=state[language_code]['about'])
        get_desc=lambda language_code=None:SimpleNamespace(
            description=state[language_code]['desc'])
        def set_about(value,language_code=None):
            state[language_code]['about']=value
        def set_desc(value,language_code=None):
            state[language_code]['desc']=value
        with patch.object(m.BOT,'get_my_short_description',
                          side_effect=get_about) as about_get, \
             patch.object(m.BOT,'get_my_description',side_effect=get_desc) as desc_get, \
             patch.object(m.BOT,'set_my_short_description',
                          side_effect=set_about) as about_set, \
             patch.object(m.BOT,'set_my_description',
                          side_effect=set_desc) as desc_set, \
             patch.object(m.BOT,'set_chat_menu_button') as menu_set, \
             patch.object(m.BOT,'get_chat_menu_button',
                          return_value=SimpleNamespace(type='commands')), \
             patch.object(m.BOT,'delete_my_commands') as commands_clear, \
             patch.object(m,'apply_approved_avatar_once') as avatar:
            m._FORMIQ_PROFILE_CONFIGURED=False
            m.configure_formiq_bot_profile()
            self.assertTrue(m._FORMIQ_PROFILE_CONFIGURED)
            self.assertEqual(about_set.call_count,2)
            self.assertEqual(desc_set.call_count,2)
            self.assertEqual(about_get.call_count,4)
            self.assertEqual(desc_get.call_count,4)
            for loc in state:
                self.assertEqual(state[loc]['about'],m.FORMIQ_BOT_ABOUT)
                self.assertEqual(state[loc]['desc'],m.FORMIQ_BOT_DESCRIPTION)
            menu_set.assert_called_once()
            commands_clear.assert_called_once()
            avatar.assert_called_once()
            m.configure_formiq_bot_profile()
            avatar.assert_called_once()

    def test_failed_read_back_is_not_marked_configured_and_retries(self):
        m=self.m
        with patch.object(m,'_sync_telegram_description',
                          side_effect=RuntimeError('API unavailable')) as sync, \
             patch.object(m.BOT,'set_chat_menu_button'), \
             patch.object(m.BOT,'get_chat_menu_button',
                          return_value=SimpleNamespace(type='commands')), \
             patch.object(m.BOT,'delete_my_commands'), \
             patch.object(m,'apply_approved_avatar_once') as avatar:
            m._FORMIQ_PROFILE_CONFIGURED=False
            m.configure_formiq_bot_profile()
            self.assertFalse(m._FORMIQ_PROFILE_CONFIGURED)
            self.assertEqual(sync.call_count,2)
            self.assertEqual(avatar.call_count,1)
            m.configure_formiq_bot_profile()
            self.assertEqual(sync.call_count,4,'Must retry after failure')

    def test_start_photo_has_the_exact_approved_caption_and_only_two_buttons(self):
        m=self.m
        expected=('Добро пожаловать в FORMIQ!\n\n'
                  'Твоя форма заслуживает умного подхода.\n\n'
                  'Тренируйся, следи за питанием и наблюдай за своим прогрессом.\n\n'
                  'Веди дневник самостоятельно или доверь Yandex AI создание персонального '
                  'плана, анализ результатов и адаптацию тренировок.')
        with patch.object(m.BOT,'set_chat_menu_button'), \
             patch.object(m.BOT,'get_chat_menu_button',
                          return_value=SimpleNamespace(type='commands')), \
             patch.object(m.BOT,'send_photo') as photo, \
             patch.object(m.BOT,'send_message') as fallback:
            m.home(123,welcome_image=True)
        photo.assert_called_once()
        fallback.assert_not_called()
        self.assertEqual(photo.call_args.kwargs['caption'],expected)
        keyboard=photo.call_args.kwargs['reply_markup'].keyboard
        self.assertEqual([item.text for row in keyboard for item in row],
                         ['FormIQ','Разбудить'])


if __name__ == '__main__':
    unittest.main()
