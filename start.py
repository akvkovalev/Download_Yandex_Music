import os
import time
import json
import webbrowser
from pathlib import Path
from datetime import datetime
from yandex_music import Client

class YandexMusicAuth:
    """Класс для управления авторизацией и токеном"""
    
    def __init__(self, token_file="yandex_token.json"):
        self.token_file = Path(token_file)
        self.token = None
        self.client = None
        
    def get_token(self):
        """Получает токен из файла или через Device Flow"""
        # Пробуем загрузить токен из файла
        if self.token_file.exists():
            print(f"🔑 Загрузка токена из файла: {self.token_file}")
            with open(self.token_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.token = data.get('access_token')
                expires_in = data.get('expires_in', 0)
                created_at = data.get('created_at', 0)
                
                # Проверяем, не истёк ли токен
                if time.time() - created_at < expires_in:
                    print(f"✅ Токен действителен (ещё {int((expires_in - (time.time() - created_at)) / 86400)} дней)")
                    return self.token
                else:
                    print("⚠️  Токен истёк, получаем новый...")
        
        # Получаем новый токен через Device Flow
        print("\n🔄 Получение нового токена через Device Flow...")
        temp_client = Client()
        
        def on_code(code):
            print(f"\n{'='*60}")
            print(f"🔐 Требуется авторизация в Яндекс Музыке")
            print(f"{'='*60}")
            print(f"1️⃣  Откройте ссылку: {code.verification_url}")
            print(f"2️⃣  Введите код: {code.user_code}")
            print(f"{'='*60}\n")
            
            # Автоматически открываем ссылку в браузере
            webbrowser.open(code.verification_url)
        
        try:
            # Получаем токен
            oauth_token = temp_client.device_auth(on_code=on_code)
            self.token = oauth_token.access_token
            
            # Сохраняем токен в файл
            token_data = {
                "access_token": self.token,
                "refresh_token": oauth_token.refresh_token,
                "expires_in": oauth_token.expires_in,
                "token_type": oauth_token.token_type,
                "created_at": time.time()
            }
            
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)
            
            print(f"\n✅ Токен успешно получен и сохранён в {self.token_file}")
            print(f"⏱️  Действителен: {oauth_token.expires_in // 86400} дней")
            
            return self.token
            
        except Exception as e:
            print(f"❌ Ошибка при получении токена: {e}")
            print("Попробуйте авторизоваться вручную через браузер")
            raise
    
    def get_client(self):
        """Возвращает авторизованный клиент"""
        if not self.token:
            self.get_token()
        
        if not self.client:
            self.client = Client(self.token).init()
            print("✅ Клиент инициализирован")
        
        return self.client

class YandexMusicSync:
    """Класс для синхронизации музыки"""
    
    def __init__(self, base_dir="yandex_music_library", delay=1, bitrate=320):
        self.base_dir = Path(base_dir)
        self.delay = delay
        self.bitrate = bitrate
        
        # Авторизация
        self.auth = YandexMusicAuth()
        self.client = self.auth.get_client()
        
        # Метаданные синхронизации
        self.metadata_file = self.base_dir / "sync_metadata.json"
        self.metadata = self.load_metadata()
        
    def load_metadata(self):
        """Загружает метаданные синхронизации"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "last_sync": None,
            "playlists": {},
            "downloaded_tracks": {}
        }
    
    def save_metadata(self):
        """Сохраняет метаданные синхронизации"""
        self.metadata["last_sync"] = datetime.now().isoformat()
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
    
    def get_track_id(self, track):
        """Получает уникальный ID трека"""
        if hasattr(track, 'track') and track.track:
            track_obj = track.track
        else:
            track_obj = track
        album_id = track_obj.albums[0].id if track_obj.albums else 0
        return f"{track_obj.id}_{album_id}"
    
    def get_track_filename(self, track_obj):
        """Формирует безопасное имя файла для трека"""
        artist_name = track_obj.artists[0].name if track_obj.artists else "Unknown Artist"
        safe_artist = "".join(c for c in artist_name if c.isalnum() or c in " ._-")
        safe_title = "".join(c for c in track_obj.title if c.isalnum() or c in " ._-")
        return f"{safe_artist} - {safe_title}.mp3"
    
    def download_track(self, track_obj, filepath):
        """Скачивает один трек"""
        try:
            track_obj.download(str(filepath), bitrate_in_kbps=self.bitrate)
            time.sleep(self.delay)
            return True
        except Exception as e:
            print(f"    ❌ Ошибка: {e}")
            return False
    
    def safe_filename(self, name):
        """Очищает имя файла/папки от недопустимых символов"""
        return "".join(c for c in name if c.isalnum() or c in " ._-")
    
    def sync_playlist(self, playlist_id, playlist_title):
        """Синхронизирует один плейлист"""
        print(f"\n📁 Синхронизация плейлиста: {playlist_title} (ID: {playlist_id})")
        
        # Получаем актуальную версию плейлиста
        playlist = self.client.users_playlists(kind=playlist_id)
        playlist_dir = self.base_dir / "playlists" / f"{playlist_id}_{self.safe_filename(playlist_title)}"
        playlist_dir.mkdir(parents=True, exist_ok=True)
        
        # Получаем текущие треки в плейлисте из API
        current_tracks = {}
        for short_track in playlist.tracks:
            if hasattr(short_track, 'track') and short_track.track:
                track_obj = short_track.track
            else:
                track_obj = short_track.fetch_track()
            
            track_id = self.get_track_id(short_track)
            filename = self.get_track_filename(track_obj)
            current_tracks[track_id] = {
                "obj": track_obj,
                "filename": filename,
                "filepath": playlist_dir / filename
            }
        
        # Получаем сохранённые треки из метаданных
        saved_tracks = self.metadata["playlists"].get(str(playlist_id), {}).get("tracks", {})
        
        # Определяем новые и удалённые треки
        new_tracks = set(current_tracks.keys()) - set(saved_tracks.keys())
        removed_tracks = set(saved_tracks.keys()) - set(current_tracks.keys())
        
        print(f"  📊 Всего треков: {len(current_tracks)}")
        print(f"  ➕ Новых: {len(new_tracks)}")
        print(f"  ➖ Удалённых: {len(removed_tracks)}")
        
        # Скачиваем новые треки
        for track_id in new_tracks:
            track_info = current_tracks[track_id]
            print(f"  ⬇️  Скачивание: {track_info['filename']}")
            
            if self.download_track(track_info["obj"], track_info["filepath"]):
                # Обновляем метаданные
                if track_id not in self.metadata["downloaded_tracks"]:
                    self.metadata["downloaded_tracks"][track_id] = {
                        "filename": track_info["filename"],
                        "playlists": []
                    }
                if playlist_id not in self.metadata["downloaded_tracks"][track_id]["playlists"]:
                    self.metadata["downloaded_tracks"][track_id]["playlists"].append(playlist_id)
        
        # Удаляем треки, которых больше нет в плейлисте
        for track_id in removed_tracks:
            if track_id in saved_tracks:
                filepath = playlist_dir / saved_tracks[track_id]
                if filepath.exists():
                    filepath.unlink()
                    print(f"  🗑️  Удалён: {saved_tracks[track_id]}")
                
                # Убираем из метаданных плейлиста
                if track_id in self.metadata["downloaded_tracks"]:
                    playlists = self.metadata["downloaded_tracks"][track_id]["playlists"]
                    if playlist_id in playlists:
                        playlists.remove(playlist_id)
                    if not playlists:
                        del self.metadata["downloaded_tracks"][track_id]
        
        # Обновляем метаданные плейлиста
        self.metadata["playlists"][str(playlist_id)] = {
            "title": playlist_title,
            "revision": playlist.revision,
            "tracks": {track_id: current_tracks[track_id]["filename"] for track_id in current_tracks.keys()}
        }
        
        return len(new_tracks), len(removed_tracks)
    
    def sync_all_playlists(self):
        """Синхронизирует все плейлисты"""
        print("=" * 60)
        print("🔄 НАЧАЛО СИНХРОНИЗАЦИИ YANDEX MUSIC")
        print("=" * 60)
        
        # Получаем список всех плейлистов
        print("\n📋 Получение списка плейлистов...")
        all_playlists = self.client.users_playlists_list()
        print(f"✅ Найдено плейлистов: {len(all_playlists)}")
        
        total_new = 0
        total_removed = 0
        
        # Синхронизируем каждый плейлист
        for i, playlist in enumerate(all_playlists, 1):
            print(f"\n[{i}/{len(all_playlists)}]")
            new, removed = self.sync_playlist(playlist.kind, playlist.title)
            total_new += new
            total_removed += removed
        
        # Сохраняем метаданные
        self.save_metadata()
        
        # Выводим итоги
        print("\n" + "=" * 60)
        print("📊 ИТОГИ СИНХРОНИЗАЦИИ")
        print("=" * 60)
        print(f"📁 Базовая папка: {self.base_dir.absolute()}")
        print(f"📦 Плейлистов обработано: {len(all_playlists)}")
        print(f"➕ Скачано новых треков: {total_new}")
        print(f"➖ Удалено треков: {total_removed}")
        print(f"🎵 Всего уникальных треков в библиотеке: {len(self.metadata['downloaded_tracks'])}")
        print(f"🕐 Последняя синхронизация: {self.metadata['last_sync']}")
        print("=" * 60)
    
    def export_library_structure(self):
        """Экспортирует структуру библиотеки в JSON"""
        structure = {
            "base_directory": str(self.base_dir.absolute()),
            "bitrate": self.bitrate,
            "sync_metadata": self.metadata,
            "directory_tree": []
        }
        
        # Строим дерево директорий
        for playlist_id, playlist_data in self.metadata["playlists"].items():
            playlist_path = self.base_dir / "playlists" / f"{playlist_id}_{self.safe_filename(playlist_data['title'])}"
            structure["directory_tree"].append({
                "playlist_id": int(playlist_id),
                "title": playlist_data["title"],
                "path": str(playlist_path.relative_to(self.base_dir) if playlist_path.exists() else None),
                "tracks": list(playlist_data["tracks"].values())
            })
        
        export_file = self.base_dir / "library_structure.json"
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(structure, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 Структура библиотеки экспортирована в: {export_file}")
        return structure

# Запуск синхронизации
if __name__ == "__main__":
    try:
        # Создаём экземпляр синхронизатора
        # При первом запуске автоматически запросит авторизацию
        sync = YandexMusicSync(
            base_dir="yandex_music_library",
            delay=1,
            bitrate=320  # Можно изменить на 192 или 0 для lossless
        )
        
        # Синхронизируем все плейлисты
        sync.sync_all_playlists()
        
        # Экспортируем структуру библиотеки
        sync.export_library_structure()
        
        print("\n✨ Синхронизация завершена!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Синхронизация прервана пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
