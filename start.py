import os
import json
import time
from pathlib import Path
from yandex_music import Client
from yandex_music.exceptions import YandexMusicError

class YandexMusicSync:
    """
    Класс для синхронизации плейлистов Яндекс Музыки с локальной файловой системой.
    """

    def __init__(self, base_dir="yandex_music_library", delay=1, bitrate=320, delete_removed=True):
        """
        Инициализация синхронизатора.

        Args:
            base_dir (str): Корневая папка для хранения музыки.
            delay (int): Задержка между запросами к API в секундах.
            bitrate (int): Битрейт для скачивания (64, 192, 320, 0 для FLAC).
            delete_removed (bool): Удалять ли локальные файлы, если трек удален из плейлиста.
        """
        self.base_dir = Path(base_dir)
        self.playlists_dir = self.base_dir / "playlists"
        self.token_file = self.base_dir / "yandex_token.json"
        self.metadata_file = self.base_dir / "sync_metadata.json"
        self.structure_file = self.base_dir / "library_structure.json"
        self.delay = delay
        self.bitrate = bitrate
        self.delete_removed = delete_removed
        self.token = None
        self.client = None

        # Создаем необходимые директории
        self.base_dir.mkdir(exist_ok=True)
        self.playlists_dir.mkdir(exist_ok=True)

    def get_token(self):
        """
        Получает токен авторизации из файла или запрашивает новый.
        """
        if self.token_file.exists():
            try:
                with open(self.token_file, "r") as f:
                    token_data = json.load(f)
                # Проверяем, не истек ли токен (с запасом)
                if token_data.get("expires_in") - int(time.time()) > 3600:
                    self.token = token_data["access_token"]
                    print("🔑 Токен загружен из файла.")
                    return
            except (json.JSONDecodeError, KeyError):
                print("⚠️ Неверный формат токена. Будет запрошен новый.")

        # Запрашиваем новый токен, если файл не найден или токен некорректен
        try:
            from yandex_music import Fletch, exceptions
            fletch = Fletch()
            # Инструкции для пользователя
            print(f"Перейдите по ссылке: {fletch.url}")
            print(f"Введите код: {fletch.code}")

            # Ожидание токена
            token_data = fletch.get_token()
            
            with open(self.token_file, "w") as f:
                json.dump(token_data, f, indent=4)
            
            self.token = token_data["access_token"]
            print("✅ Новый токен успешно получен и сохранен.")

        except ImportError:
            raise ImportError("Для получения токена установите `yandex_music[fletch]`")
        except exceptions.YandexMusicError as e:
            raise RuntimeError(f"Не удалось получить токен: {e}")

    def init_client(self):
        """
        Инициализирует клиент API Яндекс Музыки.
        """
        if not self.token:
            self.get_token()
            
            if not self.client:
                self.client = Client(self.token).init()
                print("✅ Клиент инициализирован")
            
            return self.client

    def load_metadata(self):
        """
        Загружает метаданные синхронизации из файла.
        """
        if self.metadata_file.exists():
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_metadata(self, metadata):
        """
        Сохраняет метаданные синхронизации в файл.
        """
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)

    def sanitize_filename(self, name):
        """
        Очищает имя файла от недопустимых символов.
        """
        return "".join(c for c in name if c not in r'<>:"/\|?*')

    def sync_playlist(self, playlist, metadata):
        """
        Синхронизирует отдельный плейлист.
        """
        playlist_id = f"{playlist.kind}"
        playlist_title = playlist.title.replace("/", "-")
        playlist_dir_name = f"{playlist_id}_{self.sanitize_filename(playlist_title)}"
        playlist_path = self.playlists_dir / playlist_dir_name
        playlist_path.mkdir(exist_ok=True)
        
        print(f"🔄 Синхронизация плейлиста: '{playlist_title}'")
        
        try:
            tracks = playlist.fetch_tracks()
        except YandexMusicError as e:
            print(f"   - ❌ Не удалось получить треки: {e}")
            return
            
        online_track_ids = {f"{track.track_id}" for track in tracks}
        
        # Загружаем метаданные для этого плейлиста
        playlist_meta = metadata.get(playlist_id, {})
        local_track_ids = set(playlist_meta.keys())
        
        # 1. Удаление треков, которых больше нет в плейлисте
        if self.delete_removed:
            tracks_to_delete = local_track_ids - online_track_ids
            if tracks_to_delete:
                print(f"   - 🗑️ Найдено {len(tracks_to_delete)} треков для удаления...")
                for track_id in tracks_to_delete:
                    track_info = playlist_meta.pop(track_id)
                    file_path = playlist_path / track_info["filename"]
                    if file_path.exists():
                        file_path.unlink()
                        print(f"     - 🗑️ Удален: {file_path.name}")

        # 2. Скачивание новых треков
        tracks_to_download = online_track_ids - local_track_ids
        if tracks_to_download:
            print(f"   - 📥 Найдено {len(tracks_to_download)} новых треков для скачивания...")
            for track in tracks:
                if f"{track.track_id}" in tracks_to_download:
                    artist = ", ".join(a.name for a in track.artists)
                    title = track.title
                    filename = self.sanitize_filename(f"{artist} - {title}.mp3")
                    file_path = playlist_path / filename

                    if not file_path.exists():
                        try:
                            print(f"     - 📥 Скачивание: {filename}")
                            track.download(file_path, bitrate_in_kbps=self.bitrate)
                            time.sleep(self.delay)
                            
                            # Обновляем метаданные
                            playlist_meta[f"{track.track_id}"] = {
                                "filename": filename,
                                "title": title,
                                "artist": artist,
                                "downloaded_at": time.time()
                            }
                        except Exception as e:
                            print(f"       - ❌ Ошибка скачивания: {e}")
                    else:
                        print(f"     - ✅ Файл уже существует: {filename}")
                        # Добавляем в метаданные, даже если файл уже был
                        playlist_meta[f"{track.track_id}"] = {
                            "filename": filename,
                            "title": title,
                            "artist": artist,
                            "downloaded_at": playlist_meta.get(f"{track.track_id}", {}).get("downloaded_at", time.time())
                        }

        if not tracks_to_download and not (self.delete_removed and tracks_to_delete):
            print("   - ✅ Плейлист в актуальном состоянии.")

        # Обновляем метаданные для этого плейлиста
        metadata[playlist_id] = playlist_meta


    def sync_all_playlists(self):
        """
        Синхронизирует все плейлисты пользователя.
        """
        self.init_client()
        
        print("Получение списка плейлистов...")
        try:
            playlists = self.client.users_playlists_list()
            # Добавляем "Мне нравится"
            liked_tracks_playlist = self.client.users_likes_tracks()
            playlists.insert(0, liked_tracks_playlist)
            print(f"✅ Найдено {len(playlists)} плейлистов (включая 'Мне нравится').")
            
        except YandexMusicError as e:
            print(f"❌ Не удалось получить плейлисты: {e}")
            return

        metadata = self.load_metadata()

        for playlist in playlists:
            self.sync_playlist(playlist, metadata)
            # Сохраняем прогресс после каждого плейлиста
            self.save_metadata(metadata)
            print("-" * 20)
            
        # Финальное сохранение
        self.save_metadata(metadata)


    def export_library_structure(self):
        """
        Экспортирует структуру библиотеки в JSON-файл.
        """
        library_structure = {"playlists": []}
        
        metadata = self.load_metadata()
        
        try:
            playlists = self.client.users_playlists_list()
            playlists.insert(0, self.client.users_likes_tracks())
        except Exception:
            # Если нет клиента, используем только метаданные
            playlists = []

        playlist_map = {f"{pl.kind}": pl.title for pl in playlists}

        for playlist_id, track_data in metadata.items():
            playlist_title = playlist_map.get(playlist_id, f"Неизвестный плейлист (ID: {playlist_id})")
            
            playlist_info = {
                "id": playlist_id,
                "title": playlist_title,
                "path": str(self.playlists_dir / f"{playlist_id}_{self.sanitize_filename(playlist_title)}"),
                "tracks_count": len(track_data),
                "tracks": []
            }

            for track_id, track_details in track_data.items():
                playlist_info["tracks"].append({
                    "id": track_id,
                    "filename": track_details["filename"],
                    "title": track_details["title"],
                    "artist": track_details["artist"]
                })
            
            library_structure["playlists"].append(playlist_info)
            
        with open(self.structure_file, "w", encoding="utf-8") as f:
            json.dump(library_structure, f, indent=4, ensure_ascii=False)
        
        print(f"📊 Структура библиотеки экспортирована в {self.structure_file}")


# Запуск синхронизации
if __name__ == "__main__":
    try:
        # Создаём экземпляр синхронизатора
        # При первом запуске автоматически запросит авторизацию
        sync = YandexMusicSync(
            base_dir="yandex_music_library",
            delay=1,
            bitrate=320,  # Можно изменить на 192 или 0 для lossless
            delete_removed=True # Измените на False, чтобы не удалять треки
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
