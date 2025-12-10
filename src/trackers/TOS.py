# -*- coding: utf-8 -*-
# import discord
import os
import glob
import aiofiles
import platform
import httpx
from src.console import console
from src.trackers.COMMON import COMMON
from src.trackers.UNIT3D import UNIT3D
from src.torrentcreate import CustomTorrent, torf_cb, calculate_piece_size
from datetime import datetime
from pathlib import Path


class TOS(UNIT3D):
    def __init__(self, config):
        super().__init__(config, tracker_name='TOS')
        self.config = config
        self.common = COMMON(config)
        self.tracker = 'TOS'
        self.source_flag = 'TheOldSchool'
        self.base_url = 'https://theoldschool.cc'
        self.id_url = f'{self.base_url}/api/torrents/'
        self.upload_url = f'{self.base_url}/api/torrents/upload'
        self.search_url = f'{self.base_url}/api/torrents/filter'
        self.torrent_url = f'{self.base_url}/torrents/'
        self.banned_groups = ['FL3ER', 'SUNS3T', 'WoLFHD', 'EXTREME']
        pass

    async def get_category_id(self, meta):
        tags_lower = meta['tag'].lower()
        if 'vostfr' in tags_lower or 'subfrench' in tags_lower:
            if meta['category'] == 'TV' and meta['tv_pack']:
                category_id = '9'
            else:
                category_id = {
                    'MOVIE': '6',
                    'TV': '7',
                }.get(meta['category'], '0')
        else:
            if meta['category'] == 'TV':
                category_id = '8'
            else:
                category_id = {
                    'MOVIE': '1',
                    'TV': '2',
                }.get(meta['category'], '0')
        return {'category_id': category_id}

    async def get_type_id(self, meta):
        if meta['is_disc'] == "DVD":
            type_id = '7'
        elif meta['3D'] == "3D":
            type_id = '8'
        else:
            type_id = {
                'DISC': '1',
                'REMUX': '2',
                'ENCODE': '3',
                'WEBDL': '4',
                'WEBRIP': '4',
                'HDTV': '6',
            }.get(meta['type'], '0')
        return {'type_id': type_id}

    async def get_name(self, meta):
        is_scene = bool(meta.get('scene_name'))
        base_name = meta['scene_name'] if is_scene else meta['uuid']

        if is_scene is False:
            replacements = {
                '.mkv': '',
                '.mp4': '',
                '.torrent': '',
                ' ': '.',
            }

            for old, new in replacements.items():
                base_name = base_name.replace(old, new)

        return {'name': base_name}

    async def get_additional_files(self, meta):
        files = {}
        specified_dir_path = os.path.join(meta['path'], '*.nfo')
        nfo_files = glob.glob(specified_dir_path)

        if nfo_files:
            async with aiofiles.open(nfo_files[0], 'rb') as f:
                nfo_bytes = await f.read()
            files['nfo'] = ("nfo_file.nfo", nfo_bytes, "text/plain")

        return files

    async def upload(self, meta, disctype):
        data = await self.get_data(meta)
        torrent_file_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}].torrent"

        # Set exclusive flag
        if meta['exclusive'] == True:
            data['exclusive'] = 1

        if meta['isdir']:
            # As TOS want us to keep directory at upload and upload NFO file, we need to generate a new .torrent
            console.print("[yellow]Uploading a full directory to TOS, generating a new .torrent")

            # Use Torf to create torrent as we can change filelist easily
            from data.config import config
            tracker_url = config['TRACKERS']['TOS'].get('announce_url', "https://fake.tracker").strip()
            if meta['is_disc']:
                include = []
                exclude = []
            else:
                include = ["*.mkv", "*.mp4", "*.ts", "*.nfo"]
                exclude = ["*.*", "*sample.mkv", "!sample*.*"]
            initial_size = 0
            path=Path(meta['path'])
            if os.path.isfile(path):
                initial_size = os.path.getsize(path)
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    initial_size += sum(os.path.getsize(os.path.join(root, f)) for f in files if os.path.isfile(os.path.join(root, f)))

            piece_size = calculate_piece_size(initial_size, 32768, 134217728, [], meta)

            new_torrent = CustomTorrent(
                meta=meta,
                path=path,
                trackers=[tracker_url],
                source=self.source_flag,
                private=True,
                exclude_globs=exclude,  # Ensure this is always a list
                include_globs=include,  # Ensure this is always a list
                creation_date=datetime.now(),
                comment="Le seed c'est la vie!",
                created_by="Audionut's Upload Assistant modded by mika23"
            )

            new_torrent.piece_size = piece_size
            new_torrent.validate_piece_size()
            new_torrent.generate(callback=torf_cb, interval=5)
            new_torrent.write(torrent_file_path, overwrite=True)

        else:
            console.print("[green]Uploading a single file to TOS, editing already created .torrent")
            await self.common.edit_torrent(meta, self.tracker, self.source_flag)


        # normal upload function from UNITED.py
        async with aiofiles.open(torrent_file_path, 'rb') as f:
            torrent_bytes = await f.read()
        files = {'torrent': ('torrent.torrent', torrent_bytes, 'application/x-bittorrent')}
        files.update(await self.get_additional_files(meta))
        headers = {'User-Agent': f'{meta["ua_name"]} {meta.get("current_version", "")} ({platform.system()} {platform.release()})'}
        params = {'api_token': self.api_key}

        if meta['debug'] is False:
            response_data = {}
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    response = await client.post(url=self.upload_url, files=files, data=data, headers=headers, params=params)
                    response.raise_for_status()

                    response_data = response.json()
                    meta['tracker_status'][self.tracker]['status_message'] = await self.process_response_data(response_data)
                    torrent_id = await self.get_torrent_id(response_data)

                    meta['tracker_status'][self.tracker]['torrent_id'] = torrent_id
                    await self.common.add_tracker_torrent(
                        meta,
                        self.tracker,
                        self.source_flag,
                        self.announce_url,
                        self.torrent_url + torrent_id,
                        headers=headers,
                        params=params,
                        downurl=response_data['data']
                    )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    meta['tracker_status'][self.tracker]['status_message'] = (
                        "data error: Forbidden (403). This may indicate that you do not have upload permission."
                    )
                elif e.response.status_code == 302:
                    meta['tracker_status'][self.tracker]['status_message'] = (
                        "data error: Redirect (302). This may indicate a problem with authentication. Please verify that your API key is valid."
                    )
                else:
                    meta['tracker_status'][self.tracker]['status_message'] = f'data error: HTTP {e.response.status_code} - {e.response.text}'
            except httpx.TimeoutException:
                meta['tracker_status'][self.tracker]['status_message'] = 'data error: Request timed out after 10 seconds'
            except httpx.RequestError as e:
                meta['tracker_status'][self.tracker]['status_message'] = f'data error: Unable to upload. Error: {e}.\nResponse: {response_data}'
            except Exception as e:
                meta['tracker_status'][self.tracker]['status_message'] = f'data error: It may have uploaded, go check. Error: {e}.\nResponse: {response_data}'
                return
        else:
            console.print(f'[cyan]{self.tracker} Request Data:')
            console.print(data)
            meta['tracker_status'][self.tracker]['status_message'] = f'Debug mode enabled, not uploading: {self.tracker}.'

        # console.print(meta)
