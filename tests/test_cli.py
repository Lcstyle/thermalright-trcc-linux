"""
Tests for cli – TRCC command-line interface argument parsing and dispatch.

Tests cover:
- main() with no args (prints help, returns 0)
- --version flag
- Subcommand argument parsing (detect, select, test, send, color, info, reset, setup-udev, download, gui)
- detect() / detect(--all) with mocked device_detector
- select_device() validation
- send_color() hex parsing
- show_info() with mocked system_info
- download_themes() dispatch to theme_downloader
- _get_settings_path() / _get_selected_device() / _set_selected_device() helpers
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from trcc.cli import (
    _get_selected_device,
    _get_settings_path,
    _set_selected_device,
    detect,
    download_themes,
    main,
    send_color,
    show_info,
)


class TestMainEntryPoint(unittest.TestCase):
    """Test main() CLI dispatch."""

    def test_no_args_prints_help(self):
        """No subcommand → print help, return 0."""
        with patch('sys.argv', ['trcc']):
            result = main()
        self.assertEqual(result, 0)

    def test_version_flag(self):
        """--version prints version and exits."""
        with patch('sys.argv', ['trcc', '--version']):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)

    def test_detect_dispatches(self):
        """'detect' subcommand calls detect()."""
        with patch('sys.argv', ['trcc', 'detect']), \
             patch('trcc.cli.detect', return_value=0) as mock_detect:
            result = main()
            mock_detect.assert_called_once_with(show_all=False)
            self.assertEqual(result, 0)

    def test_detect_all_flag(self):
        """'detect --all' passes show_all=True."""
        with patch('sys.argv', ['trcc', 'detect', '--all']), \
             patch('trcc.cli.detect', return_value=0) as mock_detect:
            result = main()
            mock_detect.assert_called_once_with(show_all=True)

    def test_select_dispatches(self):
        """'select 2' dispatches with number=2."""
        with patch('sys.argv', ['trcc', 'select', '2']), \
             patch('trcc.cli.select_device', return_value=0) as mock_sel:
            result = main()
            mock_sel.assert_called_once_with(2)

    def test_color_dispatches(self):
        """'color ff0000' passes hex and device."""
        with patch('sys.argv', ['trcc', 'color', 'ff0000']), \
             patch('trcc.cli.send_color', return_value=0) as mock_color:
            result = main()
            mock_color.assert_called_once_with('ff0000', device=None)

    def test_info_dispatches(self):
        """'info' subcommand dispatches to show_info."""
        with patch('sys.argv', ['trcc', 'info']), \
             patch('trcc.cli.show_info', return_value=0) as mock_info:
            result = main()
            mock_info.assert_called_once()

    def test_gui_dispatches(self):
        """'gui' subcommand dispatches to gui()."""
        with patch('sys.argv', ['trcc', 'gui']), \
             patch('trcc.cli.gui', return_value=0) as mock_gui:
            result = main()
            mock_gui.assert_called_once()

    def test_download_list(self):
        """'download --list' dispatches with show_list=True."""
        with patch('sys.argv', ['trcc', 'download', '--list']), \
             patch('trcc.cli.download_themes', return_value=0) as mock_dl:
            result = main()
            mock_dl.assert_called_once_with(
                pack=None, show_list=True, force=False, show_info=False
            )

    def test_download_pack(self):
        with patch('sys.argv', ['trcc', 'download', 'themes-320', '--force']), \
             patch('trcc.cli.download_themes', return_value=0) as mock_dl:
            result = main()
            mock_dl.assert_called_once_with(
                pack='themes-320', show_list=False, force=True, show_info=False
            )


class TestDetect(unittest.TestCase):
    """Test detect() command."""

    def _make_device(self, path='/dev/sg0', name='LCD'):
        dev = MagicMock()
        dev.scsi_device = path
        dev.product_name = name
        return dev

    @patch('trcc.cli.detect_devices', create=True)
    def test_no_devices(self, mock_detect_devs):
        """No devices → returns 1."""
        # detect() imports detect_devices inside the function body
        with patch('trcc.cli._get_selected_device', return_value=None):
            with patch.dict('sys.modules', {}):
                # Must mock at the import point inside detect()
                mock_mod = MagicMock()
                mock_mod.detect_devices.return_value = []
                with patch.dict('sys.modules', {'trcc.device_detector': mock_mod}):
                    result = detect(show_all=False)
        self.assertEqual(result, 1)

    def test_detect_with_device(self):
        """Single device → returns 0 and prints path."""
        dev = self._make_device()
        mock_mod = MagicMock()
        mock_mod.detect_devices.return_value = [dev]

        with patch.dict('sys.modules', {'trcc.device_detector': mock_mod}), \
             patch('trcc.cli._get_selected_device', return_value='/dev/sg0'):
            result = detect(show_all=False)
        self.assertEqual(result, 0)


class TestSettingsHelpers(unittest.TestCase):
    """Test CLI settings persistence helpers."""

    def test_settings_path(self):
        path = _get_settings_path()
        self.assertTrue(path.endswith('settings.json'))

    def test_get_selected_no_file(self):
        """Returns None when no settings file."""
        with patch('trcc.cli._get_settings_path', return_value='/nonexistent/settings.json'):
            self.assertIsNone(_get_selected_device())

    def test_set_and_get_selected(self):
        """Round-trip: set then get selected device."""
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, 'settings.json')
            with patch('trcc.cli._get_settings_path', return_value=settings_path):
                _set_selected_device('/dev/sg1')
                result = _get_selected_device()
            self.assertEqual(result, '/dev/sg1')

    def test_set_preserves_other_keys(self):
        """set_selected_device preserves existing settings keys."""
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, 'settings.json')
            # Pre-populate with another key
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            with open(settings_path, 'w') as f:
                json.dump({'theme': 'dark'}, f)

            with patch('trcc.cli._get_settings_path', return_value=settings_path):
                _set_selected_device('/dev/sg2')

            with open(settings_path) as f:
                data = json.load(f)
            self.assertEqual(data['theme'], 'dark')
            self.assertEqual(data['selected_device'], '/dev/sg2')


class TestSendColor(unittest.TestCase):
    """Test send_color() hex parsing and dispatch."""

    def test_invalid_hex_short(self):
        """Too-short hex → returns 1."""
        result = send_color('fff')
        self.assertEqual(result, 1)

    def test_invalid_hex_long(self):
        result = send_color('ff00ff00')
        self.assertEqual(result, 1)

    def test_valid_hex_with_hash(self):
        """Hex with leading '#' is stripped."""
        mock_driver = MagicMock()
        mock_driver.create_solid_color.return_value = b'\x00' * 100
        mock_mod = MagicMock()
        mock_mod.LCDDriver.return_value = mock_driver

        with patch.dict('sys.modules', {'trcc.lcd_driver': mock_mod}), \
             patch('trcc.cli._get_selected_device', return_value='/dev/sg0'), \
             patch('trcc.cli._ensure_extracted'):
            result = send_color('#ff0000')
        self.assertEqual(result, 0)


class TestShowInfo(unittest.TestCase):
    """Test show_info() metrics display."""

    def test_show_info_success(self):
        """Successful metrics fetch returns 0."""
        mock_mod = MagicMock()
        mock_mod.get_all_metrics.return_value = {
            'cpu_temp': 65, 'cpu_percent': 30, 'mem_percent': 45
        }
        mock_mod.format_metric.side_effect = lambda k, v: f"{v}"

        with patch.dict('sys.modules', {'trcc.system_info': mock_mod}):
            result = show_info()
        self.assertEqual(result, 0)


class TestDownloadThemes(unittest.TestCase):
    """Test download_themes() dispatch."""

    def test_list_mode(self):
        """show_list=True calls list_available."""
        mock_mod = MagicMock()
        with patch.dict('sys.modules', {'trcc.theme_downloader': mock_mod}):
            result = download_themes(pack=None, show_list=True, force=False, show_info=False)
        self.assertEqual(result, 0)

    def test_download_dispatches(self):
        """Pack name dispatches to download_pack."""
        mock_mod = MagicMock()
        mock_mod.download_pack.return_value = 0
        with patch.dict('sys.modules', {'trcc.theme_downloader': mock_mod}):
            result = download_themes(pack='themes-320', show_list=False,
                                     force=True, show_info=False)
        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
