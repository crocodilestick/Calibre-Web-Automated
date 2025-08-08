import json
import os
from pathlib import Path
from typing import Dict, List, Optional

class ThemeManager:
    """Manages theme configuration and switching"""
    
    def __init__(self, themes_file_path: str = None):
        if themes_file_path is None:
            themes_file_path = os.path.join(os.path.dirname(__file__), 'static', 'themes', 'themes.json')
        self.themes_file_path = themes_file_path
        self._themes = None
    
    def load_themes(self) -> Dict:
        """Load themes from the configuration file"""
        if self._themes is None:
            try:
                with open(self.themes_file_path, 'r') as f:
                    self._themes = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                # Fallback to default themes if file doesn't exist or is invalid
                self._themes = {
                    "themes": [
                        {
                            "id": 0,
                            "name": "default",
                            "description": "Default Calibre-Web theme",
                            "css_files": ["style.css"],
                            "body_class": "",
                            "icon": "glyphicon-book"
                        },
                        {
                            "id": 1,
                            "name": "caliblur",
                            "description": "CaliBlur theme with blur effects",
                            "css_files": ["caliBlur.css", "caliBlur_override.css"],
                            "body_class": "blur",
                            "icon": "glyphicon-sunglasses"
                        }
                    ]
                }
        return self._themes
    
    def get_theme_by_id(self, theme_id: int) -> Optional[Dict]:
        """Get theme configuration by ID"""
        themes = self.load_themes()
        for theme in themes.get('themes', []):
            if theme.get('id') == theme_id:
                return theme
        return None
    
    def get_current_theme(self, current_theme_id: int) -> Dict:
        """Get current theme configuration"""
        theme = self.get_theme_by_id(current_theme_id)
        if theme is None:
            # Fallback to default theme if current theme doesn't exist
            return self.get_theme_by_id(0) or {
                "id": 0,
                "name": "default",
                "description": "Default Calibre-Web theme",
                "css_files": ["style.css"],
                "body_class": "",
                "icon": "glyphicon-book"
            }
        return theme
    
    def get_next_theme_id(self, current_theme_id: int) -> int:
        """Get the next theme ID in the cycle"""
        themes = self.load_themes()
        theme_ids = [theme.get('id') for theme in themes.get('themes', [])]
        
        if not theme_ids:
            return 0
        
        try:
            current_index = theme_ids.index(current_theme_id)
            next_index = (current_index + 1) % len(theme_ids)
            return theme_ids[next_index]
        except ValueError:
            # If current theme ID not found, return first theme
            return theme_ids[0] if theme_ids else 0
    
    def get_all_themes(self) -> List[Dict]:
        """Get all available themes"""
        themes = self.load_themes()
        return themes.get('themes', [])
    
    def validate_theme(self, theme: Dict) -> bool:
        """Validate theme configuration"""
        required_fields = ['id', 'name', 'description', 'css_files']
        return all(field in theme for field in required_fields)

# Global theme manager instance
theme_manager = ThemeManager()
