"""
Tests for core.controllers – MVC business logic controllers.

Tests cover:
- ThemeController: set_directories, load/filter/select, callbacks
- DeviceController: detect, select, send_image_async, callbacks
- VideoController: load, play/pause/stop, tick, seek, frame interval
- OverlayController: enable/disable, add/remove/update elements, render
- FormCZTVController: initialization, resolution, rotation, brightness,
  theme loading, working dir lifecycle, cleanup
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from trcc.core.models import (
    DeviceInfo,
    DeviceModel,
    OverlayElement,
    OverlayElementType,
    OverlayModel,
    PlaybackState,
    ThemeInfo,
    ThemeModel,
    ThemeType,
    VideoModel,
    VideoState,
)
from trcc.core.controllers import (
    DeviceController,
    FormCZTVController,
    OverlayController,
    ThemeController,
    VideoController,
)


# =============================================================================
# ThemeController
# =============================================================================

class TestThemeController(unittest.TestCase):
    """Test ThemeController business logic."""

    def setUp(self):
        self.ctrl = ThemeController()

    def test_initial_state(self):
        self.assertIsInstance(self.ctrl.model, ThemeModel)
        self.assertIsNone(self.ctrl.get_selected())
        self.assertEqual(self.ctrl.get_themes(), [])

    def test_set_directories(self):
        """set_directories propagates to model."""
        local = Path('/tmp/themes')
        web = Path('/tmp/web')
        masks = Path('/tmp/masks')
        self.ctrl.set_directories(local_dir=local, web_dir=web, masks_dir=masks)
        self.assertEqual(self.ctrl.model.local_theme_dir, local)
        self.assertEqual(self.ctrl.model.cloud_web_dir, web)
        self.assertEqual(self.ctrl.model.cloud_masks_dir, masks)

    def test_set_filter(self):
        """set_filter updates model and fires callback."""
        fired = []
        self.ctrl.on_filter_changed = lambda mode: fired.append(mode)
        self.ctrl.set_filter('user')
        self.assertEqual(self.ctrl.model.filter_mode, 'user')
        self.assertEqual(fired, ['user'])

    def test_set_category(self):
        """set_category passes through to model, 'all' maps to None."""
        self.ctrl.set_category('b')
        self.assertEqual(self.ctrl.model.category_filter, 'b')
        self.ctrl.set_category('all')
        self.assertIsNone(self.ctrl.model.category_filter)

    def test_select_theme_fires_callback(self):
        """Selecting a theme fires on_theme_selected."""
        fired = []
        self.ctrl.on_theme_selected = lambda t: fired.append(t)
        theme = ThemeInfo(name='Test')
        self.ctrl.select_theme(theme)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].name, 'Test')

    def test_load_local_themes_with_dir(self):
        """Loading themes from a directory with valid themes."""
        with tempfile.TemporaryDirectory() as tmp:
            theme_dir = Path(tmp) / 'Theme1'
            theme_dir.mkdir()
            (theme_dir / '00.png').write_bytes(b'PNG')
            (theme_dir / 'Theme.png').write_bytes(b'PNG')

            self.ctrl.set_directories(local_dir=Path(tmp))
            self.ctrl.load_local_themes((320, 320))
            themes = self.ctrl.get_themes()
            self.assertEqual(len(themes), 1)
            self.assertEqual(themes[0].name, 'Theme1')

    def test_on_themes_loaded_callback(self):
        """on_themes_loaded fires after load."""
        fired = []
        self.ctrl.on_themes_loaded = lambda themes: fired.append(len(themes))

        with tempfile.TemporaryDirectory() as tmp:
            theme_dir = Path(tmp) / 'T1'
            theme_dir.mkdir()
            (theme_dir / '00.png').write_bytes(b'x')

            self.ctrl.set_directories(local_dir=Path(tmp))
            self.ctrl.load_local_themes()

        self.assertEqual(len(fired), 1)

    def test_categories_dict(self):
        """CATEGORIES has expected keys."""
        self.assertIn('all', ThemeController.CATEGORIES)
        self.assertIn('a', ThemeController.CATEGORIES)


# =============================================================================
# DeviceController
# =============================================================================

class TestDeviceController(unittest.TestCase):
    """Test DeviceController device management."""

    def setUp(self):
        self.ctrl = DeviceController()

    def test_initial_state(self):
        self.assertEqual(self.ctrl.get_devices(), [])
        self.assertIsNone(self.ctrl.get_selected())

    def test_select_device(self):
        """Selecting a device fires callback."""
        fired = []
        self.ctrl.on_device_selected = lambda d: fired.append(d)
        dev = DeviceInfo(name='LCD', path='/dev/sg0')
        self.ctrl.select_device(dev)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].path, '/dev/sg0')

    def test_send_started_callback(self):
        """send_image_async fires on_send_started."""
        started = []
        self.ctrl.on_send_started = lambda: started.append(True)

        # Mock the model so send doesn't actually hit hardware
        self.ctrl.model._send_busy = False
        self.ctrl.model.selected_device = DeviceInfo(name='LCD', path='/dev/sg0')

        with patch.object(self.ctrl.model, 'send_image'):
            self.ctrl.send_image_async(b'\x00' * 100, 10, 10)

        self.assertTrue(started)

    def test_send_skipped_when_busy(self):
        """send_image_async is a no-op when model is busy."""
        started = []
        self.ctrl.on_send_started = lambda: started.append(True)
        self.ctrl.model._send_busy = True
        self.ctrl.send_image_async(b'\x00', 1, 1)
        self.assertEqual(started, [])  # Never fired

    def test_devices_changed_callback(self):
        """on_devices_changed fires when model's callback triggers."""
        fired = []
        self.ctrl.on_devices_changed = lambda devs: fired.append(len(devs))
        # Simulate model firing its callback
        self.ctrl.model.devices = [DeviceInfo(name='A', path='/dev/sg0')]
        self.ctrl._on_model_devices_changed()
        self.assertEqual(fired, [1])


# =============================================================================
# VideoController
# =============================================================================

class TestVideoController(unittest.TestCase):
    """Test VideoController playback logic."""

    def setUp(self):
        self.ctrl = VideoController()

    def test_initial_state(self):
        self.assertFalse(self.ctrl.is_playing())
        self.assertFalse(self.ctrl.has_frames())

    def test_set_target_size(self):
        self.ctrl.set_target_size(480, 480)
        self.assertEqual(self.ctrl.model.target_size, (480, 480))

    def test_play_pause_stop(self):
        """Play/pause/stop update model state."""
        # Need a mock player
        self.ctrl.model._player = MagicMock()
        self.ctrl.model.state.total_frames = 10

        self.ctrl.play()
        self.assertTrue(self.ctrl.is_playing())

        self.ctrl.pause()
        self.assertFalse(self.ctrl.is_playing())

        self.ctrl.play()
        self.ctrl.stop()
        self.assertFalse(self.ctrl.is_playing())

    def test_toggle_play_pause(self):
        """toggle_play_pause switches states."""
        self.ctrl.model._player = MagicMock()
        self.ctrl.model.state.total_frames = 10

        self.ctrl.toggle_play_pause()  # stopped → playing
        self.assertTrue(self.ctrl.is_playing())

        self.ctrl.toggle_play_pause()  # playing → paused
        self.assertFalse(self.ctrl.is_playing())

    def test_seek(self):
        self.ctrl.model.state.total_frames = 100
        self.ctrl.seek(50.0)
        self.assertEqual(self.ctrl.model.state.current_frame, 50)

    def test_tick_when_not_playing(self):
        """tick() returns None when not playing."""
        self.assertIsNone(self.ctrl.tick())

    def test_tick_advances_frame(self):
        """tick() advances frame and calls on_send_frame."""
        sent = []
        self.ctrl.on_send_frame = lambda f: sent.append(f)

        # Set up playing state with preloaded frames
        fake_frame = MagicMock()
        self.ctrl.model.frames = [fake_frame, fake_frame]
        self.ctrl.model.state.total_frames = 2
        self.ctrl.model.state.state = PlaybackState.PLAYING
        self.ctrl.model.state.current_frame = 0

        frame = self.ctrl.tick()
        self.assertIsNotNone(frame)
        self.assertEqual(len(sent), 1)  # LCD_SEND_INTERVAL=1

    def test_get_frame_interval(self):
        """Default 16fps → ~62ms."""
        ms = self.ctrl.get_frame_interval()
        self.assertGreater(ms, 0)
        self.assertEqual(ms, 62)  # 1000/16 = 62

    def test_on_video_loaded_callback(self):
        """on_video_loaded fires after successful load."""
        fired = []
        self.ctrl.on_video_loaded = lambda s: fired.append(s)

        # Mock load to succeed
        with patch.object(self.ctrl.model, 'load', return_value=True):
            self.ctrl.load(Path('fake.mp4'))

        self.assertEqual(len(fired), 1)


# =============================================================================
# OverlayController
# =============================================================================

class TestOverlayController(unittest.TestCase):
    """Test OverlayController overlay management."""

    def setUp(self):
        self.ctrl = OverlayController()

    def test_initial_state(self):
        self.assertFalse(self.ctrl.is_enabled())
        self.assertEqual(self.ctrl.get_elements(), [])

    def test_enable_disable(self):
        self.ctrl.enable(True)
        self.assertTrue(self.ctrl.is_enabled())
        self.ctrl.enable(False)
        self.assertFalse(self.ctrl.is_enabled())

    def test_set_target_size(self):
        self.ctrl.set_target_size(480, 480)
        self.assertEqual(self.ctrl.model.target_size, (480, 480))

    def test_add_element(self):
        elem = OverlayElement(element_type=OverlayElementType.TEXT, text='Hello')
        self.ctrl.add_element(elem)
        self.assertEqual(len(self.ctrl.get_elements()), 1)
        self.assertEqual(self.ctrl.get_elements()[0].text, 'Hello')

    def test_remove_element(self):
        self.ctrl.add_element(OverlayElement(text='A'))
        self.ctrl.add_element(OverlayElement(text='B'))
        self.ctrl.remove_element(0)
        self.assertEqual(len(self.ctrl.get_elements()), 1)
        self.assertEqual(self.ctrl.get_elements()[0].text, 'B')

    def test_update_element(self):
        self.ctrl.add_element(OverlayElement(text='old'))
        self.ctrl.update_element(0, OverlayElement(text='new'))
        self.assertEqual(self.ctrl.get_elements()[0].text, 'new')

    def test_on_config_changed_callback(self):
        """on_config_changed fires on add/remove/update."""
        fired = []
        self.ctrl.on_config_changed = lambda: fired.append(True)
        self.ctrl.add_element(OverlayElement(text='x'))
        self.ctrl.update_element(0, OverlayElement(text='y'))
        self.ctrl.remove_element(0)
        self.assertEqual(len(fired), 3)

    def test_update_metrics(self):
        """update_metrics stores metrics for render."""
        self.ctrl.update_metrics({'cpu_temp': 65})
        self.assertEqual(self.ctrl._metrics['cpu_temp'], 65)

    def test_render_disabled_returns_background(self):
        """When disabled, render returns background unchanged."""
        bg = MagicMock()
        self.ctrl.model.background = bg
        result = self.ctrl.render()
        self.assertIs(result, bg)


# =============================================================================
# FormCZTVController
# =============================================================================

class TestFormCZTVController(unittest.TestCase):
    """Test FormCZTVController main application controller."""

    def setUp(self):
        # Patch paths module to avoid file I/O
        self.patches = [
            patch('trcc.core.controllers.get_saved_resolution', return_value=(320, 320)),
            patch('trcc.core.controllers.save_resolution'),
            patch('trcc.core.controllers.ensure_themes_extracted'),
            patch('trcc.core.controllers.ensure_web_extracted'),
            patch('trcc.core.controllers.ensure_web_masks_extracted'),
            patch('trcc.core.controllers.get_web_dir', return_value='/tmp/web'),
            patch('trcc.core.controllers.get_web_masks_dir', return_value='/tmp/masks'),
        ]
        for p in self.patches:
            p.start()

        self.ctrl = FormCZTVController()

    def tearDown(self):
        self.ctrl.cleanup()
        for p in self.patches:
            p.stop()

    def test_initial_resolution(self):
        self.assertEqual(self.ctrl.lcd_width, 320)
        self.assertEqual(self.ctrl.lcd_height, 320)

    def test_working_dir_created(self):
        """Constructor creates a temp working directory."""
        self.assertTrue(self.ctrl.working_dir.exists())
        self.assertTrue(self.ctrl.working_dir.is_dir())

    def test_cleanup_removes_working_dir(self):
        """cleanup() removes the working directory."""
        wd = self.ctrl.working_dir
        self.assertTrue(wd.exists())
        self.ctrl.cleanup()
        self.assertFalse(wd.exists())

    def test_set_resolution(self):
        """set_resolution updates width/height and sub-controllers."""
        fired = []
        self.ctrl.on_resolution_changed = lambda w, h: fired.append((w, h))
        self.ctrl.set_resolution(480, 480)
        self.assertEqual(self.ctrl.lcd_width, 480)
        self.assertEqual(self.ctrl.lcd_height, 480)
        self.assertEqual(self.ctrl.video.model.target_size, (480, 480))
        self.assertEqual(self.ctrl.overlay.model.target_size, (480, 480))
        self.assertEqual(fired, [(480, 480)])

    def test_set_resolution_no_op_same(self):
        """set_resolution is a no-op if already at that resolution."""
        fired = []
        self.ctrl.on_resolution_changed = lambda w, h: fired.append((w, h))
        self.ctrl.set_resolution(320, 320)
        self.assertEqual(fired, [])  # No callback

    def test_set_rotation(self):
        """set_rotation wraps at 360."""
        self.ctrl.set_rotation(90)
        self.assertEqual(self.ctrl.rotation, 90)
        self.ctrl.set_rotation(450)
        self.assertEqual(self.ctrl.rotation, 90)

    def test_set_brightness_clamps(self):
        """set_brightness clamps to 0-100."""
        self.ctrl.set_brightness(150)
        self.assertEqual(self.ctrl.brightness, 100)
        self.ctrl.set_brightness(-10)
        self.assertEqual(self.ctrl.brightness, 0)

    def test_auto_send_default(self):
        self.assertTrue(self.ctrl.auto_send)

    def test_sub_controllers_initialized(self):
        """All sub-controllers are proper types."""
        self.assertIsInstance(self.ctrl.themes, ThemeController)
        self.assertIsInstance(self.ctrl.devices, DeviceController)
        self.assertIsInstance(self.ctrl.video, VideoController)
        self.assertIsInstance(self.ctrl.overlay, OverlayController)

    def test_play_pause(self):
        """play_pause delegates to video controller."""
        with patch.object(self.ctrl.video, 'toggle_play_pause') as mock:
            self.ctrl.play_pause()
            mock.assert_called_once()

    def test_seek_video(self):
        with patch.object(self.ctrl.video, 'seek') as mock:
            self.ctrl.seek_video(50.0)
            mock.assert_called_once_with(50.0)

    def test_is_video_playing(self):
        with patch.object(self.ctrl.video, 'is_playing', return_value=False) as mock:
            self.assertFalse(self.ctrl.is_video_playing())

    def test_on_device_selected_updates_resolution(self):
        """Device selection triggers resolution update if different."""
        dev = DeviceInfo(name='LCD', path='/dev/sg0', resolution=(480, 480))
        with patch.object(self.ctrl, 'set_resolution') as mock_res:
            self.ctrl._on_device_selected(dev)
            mock_res.assert_called_once_with(480, 480)

    def test_on_device_selected_same_resolution(self):
        """No resolution update when device matches current."""
        dev = DeviceInfo(name='LCD', path='/dev/sg0', resolution=(320, 320))
        with patch.object(self.ctrl, 'set_resolution') as mock_res:
            self.ctrl._on_device_selected(dev)
            mock_res.assert_not_called()

    def test_status_update_callback(self):
        """_update_status fires on_status_update."""
        fired = []
        self.ctrl.on_status_update = lambda s: fired.append(s)
        self.ctrl._update_status('testing')
        self.assertEqual(fired, ['testing'])

    def test_error_callback(self):
        """_handle_error fires on_error."""
        errors = []
        self.ctrl.on_error = lambda e: errors.append(e)
        self.ctrl._handle_error('broke')
        self.assertEqual(errors, ['broke'])

    def test_send_current_image_no_image(self):
        """send_current_image with no image is a no-op."""
        self.ctrl.current_image = None
        self.ctrl.send_current_image()  # Should not raise

    def test_clear_working_dir(self):
        """_clear_working_dir recreates empty directory."""
        (self.ctrl.working_dir / 'junk.txt').write_text('x')
        self.ctrl._clear_working_dir()
        self.assertTrue(self.ctrl.working_dir.exists())
        self.assertEqual(list(self.ctrl.working_dir.iterdir()), [])

    def test_copy_theme_to_working_dir(self):
        """Files are copied from source to working dir."""
        with tempfile.TemporaryDirectory() as src:
            (Path(src) / '00.png').write_bytes(b'PNG_DATA')
            (Path(src) / 'config1.dc').write_bytes(b'\xdc\x00')

            self.ctrl._copy_theme_to_working_dir(Path(src))

            self.assertTrue((self.ctrl.working_dir / '00.png').exists())
            self.assertTrue((self.ctrl.working_dir / 'config1.dc').exists())


class TestFormCZTVControllerRotation(unittest.TestCase):
    """Test _apply_rotation and _apply_brightness image transforms."""

    def setUp(self):
        self.patches = [
            patch('trcc.core.controllers.get_saved_resolution', return_value=(320, 320)),
            patch('trcc.core.controllers.save_resolution'),
            patch('trcc.core.controllers.ensure_themes_extracted'),
            patch('trcc.core.controllers.ensure_web_extracted'),
            patch('trcc.core.controllers.ensure_web_masks_extracted'),
            patch('trcc.core.controllers.get_web_dir', return_value='/tmp/web'),
            patch('trcc.core.controllers.get_web_masks_dir', return_value='/tmp/masks'),
        ]
        for p in self.patches:
            p.start()
        self.ctrl = FormCZTVController()

    def tearDown(self):
        self.ctrl.cleanup()
        for p in self.patches:
            p.stop()

    def test_apply_rotation_0(self):
        """0° rotation returns image unchanged."""
        img = MagicMock()
        self.ctrl.rotation = 0
        result = self.ctrl._apply_rotation(img)
        self.assertIs(result, img)

    def test_apply_rotation_non_zero(self):
        """Non-zero rotation calls transpose."""
        img = MagicMock()
        img.transpose.return_value = MagicMock()
        self.ctrl.rotation = 180
        result = self.ctrl._apply_rotation(img)
        img.transpose.assert_called_once()

    def test_apply_brightness_full(self):
        """100% brightness returns image unchanged."""
        img = MagicMock()
        self.ctrl.brightness = 100
        result = self.ctrl._apply_brightness(img)
        self.assertIs(result, img)


if __name__ == '__main__':
    unittest.main()
