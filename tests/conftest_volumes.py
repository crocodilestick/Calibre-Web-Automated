# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Docker Volume support for Docker-in-Docker test environments.

This module provides fixtures and helpers for running integration tests
inside Docker containers (DinD scenarios) where bind mounts don't work.
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Generator, List, Union
import pytest


def volume_copy(src: Union[Path, str], dst: Union['VolumePath', Path, str]):
    """
    Copy file that works with both regular paths and VolumePath objects.
    
    This is a drop-in replacement for shutil.copy2() in volume mode.
    """
    from pathlib import Path as PathLib
    
    # If destination is a VolumePath, use its volume helper
    if isinstance(dst, VolumePath):
        dst.volume_helper.copy_to(Path(src), dst.filename)
    # Otherwise use regular shutil
    else:
        shutil.copy2(src, dst)


class VolumePath:
    """
    Path-like wrapper for a file in a Docker volume.
    
    Provides Path-compatible interface while operating on Docker volumes.
    """
    def __init__(self, volume_helper: 'VolumeHelper', filename: str):
        self.volume_helper = volume_helper
        self.filename = filename
        self._name = Path(filename).name
    
    @property
    def name(self) -> str:
        """Return the filename (Path-compatible)."""
        return self._name
    
    def exists(self) -> bool:
        """Check if file exists in volume (Path-compatible)."""
        return self.volume_helper.file_exists(self.filename)
    
    def is_dir(self) -> bool:
        """Check if path is a directory."""
        # Use docker run to check if it's a directory
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{self.volume_helper.volume_name}:{self.volume_helper.mount_path}",
             "alpine", "test", "-d", f"{self.volume_helper.mount_path}/{self.filename}"],
            capture_output=True
        )
        return result.returncode == 0
    
    def mkdir(self, parents: bool = False, exist_ok: bool = False):
        """Create directory in volume (Path-compatible)."""
        self.volume_helper.mkdir(self.filename, parents=parents, exist_ok=exist_ok)
    
    def write_text(self, content: str, encoding: str = 'utf-8'):
        """Write text content to file in volume."""
        import tempfile
        temp_file = Path(tempfile.mktemp())
        temp_file.write_text(content, encoding=encoding)
        try:
            self.volume_helper.copy_to(temp_file, self.filename)
        finally:
            temp_file.unlink(missing_ok=True)
    
    def read_to_local(self, temp_dir: Path) -> Path:
        """Extract file from volume to local temp directory for reading."""
        return self.volume_helper.read_to_temp(self.filename, temp_dir)
    
    def glob(self, pattern: str):
        """Find files matching pattern in this directory."""
        # Construct full pattern path
        search_pattern = f"{self.filename}/{pattern}" if self.filename else pattern
        return self.volume_helper.glob(search_pattern)
    
    def iterdir(self):
        """Iterate over items in this directory (Path-compatible)."""
        # List items in this subdirectory
        search_path = f"{self.volume_helper.mount_path}/{self.filename}" if self.filename else self.volume_helper.mount_path
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{self.volume_helper.volume_name}:{self.volume_helper.mount_path}",
             "alpine", "find", search_path, "-maxdepth", "1", "-mindepth", "1"],
            capture_output=True, text=True, check=True
        )
        items = result.stdout.strip().split('\n')
        for item in items:
            if item.strip():
                # Get just the filename relative to the volume root
                name = item.replace(f"{self.volume_helper.mount_path}/", "")
                yield VolumePath(self.volume_helper, name)
    
    def __truediv__(self, other):
        """Support path / "file" syntax."""
        new_path = f"{self.filename}/{other}" if self.filename else str(other)
        return VolumePath(self.volume_helper, new_path)
    
    def __str__(self) -> str:
        """
        Return string representation.
        
        Note: For database operations in volume mode, use read_to_local() first.
        """
        return f"{self.volume_helper.mount_path}/{self.filename}"
    
    def __fspath__(self) -> str:
        """Return filesystem path (os.PathLike protocol)."""
        return str(self)


class VolumeHelper:
    """
    Helper to interact with Docker volumes using docker cp.
    
    Provides Path-compatible interface for Docker volume operations in DinD scenarios.
    """
    
    def __init__(self, volume_name: str, mount_path: str = "/volume"):
        self.volume_name = volume_name
        self.mount_path = mount_path
        self._name = Path(mount_path).name
    
    @property
    def name(self) -> str:
        """Return the volume/folder name (Path-compatible)."""
        return self._name
    
    def copy_to(self, source: Path, dest_name: str = None):
        """Copy a file from host into the Docker volume."""
        if dest_name is None:
            dest_name = source.name
        
        temp_name = f"temp-vol-copy-{uuid.uuid4().hex[:8]}"
        try:
            subprocess.run(
                ["docker", "create", "--name", temp_name, 
                 "-v", f"{self.volume_name}:{self.mount_path}",
                 "alpine", "true"],
                check=True, capture_output=True
            )
            subprocess.run(
                ["docker", "cp", str(source), f"{temp_name}:{self.mount_path}/{dest_name}"],
                check=True, capture_output=True
            )
        finally:
            subprocess.run(["docker", "rm", "-f", temp_name], capture_output=True)
    
    def copy_from(self, filename: str, dest_path: Path):
        """Copy a file from the Docker volume to host."""
        temp_name = f"temp-vol-extract-{uuid.uuid4().hex[:8]}"
        try:
            subprocess.run(
                ["docker", "create", "--name", temp_name,
                 "-v", f"{self.volume_name}:{self.mount_path}",
                 "alpine", "true"],
                check=True, capture_output=True
            )
            subprocess.run(
                ["docker", "cp", f"{temp_name}:{self.mount_path}/{filename}", str(dest_path)],
                check=True, capture_output=True
            )
        finally:
            subprocess.run(["docker", "rm", "-f", temp_name], capture_output=True)
    
    def file_exists(self, filename: str) -> bool:
        """Check if a file exists in the volume."""
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{self.volume_name}:{self.mount_path}",
             "alpine", "test", "-f", f"{self.mount_path}/{filename}"],
            capture_output=True
        )
        return result.returncode == 0
    
    def list_files(self, pattern: str = "*") -> List[str]:
        """List files in the volume matching pattern."""
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{self.volume_name}:{self.mount_path}",
             "alpine", "find", self.mount_path, "-name", pattern, "-type", "f"],
            capture_output=True, text=True, check=True
        )
        files = result.stdout.strip().split('\n')
        return [f.replace(f"{self.mount_path}/", "") for f in files if f.strip()]
    
    def iterdir(self):
        """Iterate over all items (files and directories) in the volume (Path-compatible)."""
        # List everything in the mount path (maxdepth 1 = immediate children only)
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{self.volume_name}:{self.mount_path}",
             "alpine", "find", self.mount_path, "-maxdepth", "1", "-mindepth", "1"],
            capture_output=True, text=True, check=True
        )
        items = result.stdout.strip().split('\n')
        for item in items:
            if item.strip():
                # Remove mount path prefix
                name = item.replace(f"{self.mount_path}/", "")
                yield VolumePath(self, name)
    
    def glob(self, pattern: str):
        """Find files matching pattern (Path-compatible)."""
        files = self.list_files(pattern)
        for filename in files:
            yield VolumePath(self, filename)
    
    def mkdir(self, dirname: str, parents: bool = False, exist_ok: bool = False):
        """Create a directory in the volume."""
        # Build the mkdir command
        cmd = ["docker", "run", "--rm",
               "-v", f"{self.volume_name}:{self.mount_path}",
               "alpine", "mkdir"]
        
        if parents:
            cmd.append("-p")
        
        cmd.append(f"{self.mount_path}/{dirname}")
        
        result = subprocess.run(cmd, capture_output=True)
        
        if result.returncode != 0 and not exist_ok:
            # Check if it failed because directory exists
            check = subprocess.run(
                ["docker", "run", "--rm",
                 "-v", f"{self.volume_name}:{self.mount_path}",
                 "alpine", "test", "-d", f"{self.mount_path}/{dirname}"],
                capture_output=True
            )
            if check.returncode == 0 and exist_ok:
                return  # Directory exists and exist_ok=True
            raise OSError(f"Failed to create directory {dirname}: {result.stderr.decode()}")
    
    def read_to_temp(self, filename: str, temp_dir: Path) -> Path:
        """
        Copy a file from volume to a temporary location for reading.
        
        Useful for reading database files, logs, etc.
        Returns the local path to the extracted file.
        """
        local_path = temp_dir / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.copy_from(filename, local_path)
        return local_path
    
    def __truediv__(self, other):
        """Support path-like syntax: volume / "file.epub" returns VolumePath."""
        return VolumePath(self, str(other))
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.mount_path
    
    def __fspath__(self) -> str:
        """Return filesystem path (os.PathLike protocol)."""
        return self.mount_path


@pytest.fixture(scope="session")
def test_volumes_dind():
    """Create Docker volumes for ingest and library folders."""
    session_id = uuid.uuid4().hex[:8]
    ingest_volume = f"cwa-test-ingest-{session_id}"
    library_volume = f"cwa-test-library-{session_id}"
    
    print(f"\n🔵 Creating Docker volumes (session {session_id})")
    subprocess.run(["docker", "volume", "create", ingest_volume], check=True, capture_output=True)
    subprocess.run(["docker", "volume", "create", library_volume], check=True, capture_output=True)
    
    yield (ingest_volume, library_volume)
    
    print(f"\n🔵 Cleaning up Docker volumes (session {session_id})")
    subprocess.run(["docker", "volume", "rm", "-f", ingest_volume], capture_output=True)
    subprocess.run(["docker", "volume", "rm", "-f", library_volume], capture_output=True)


@pytest.fixture(scope="session")
def cwa_container_dind(test_volumes_dind):
    """Start CWA container with Docker volumes."""
    ingest_volume, library_volume = test_volumes_dind
    container_name = "temp-cwa-test-suite"
    
    print(f"\n🔵 Starting CWA container with volumes...")
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    
    subprocess.run([
        "docker", "run", "-d",
        "--name", container_name,
        "-e", "PUID=1000",
        "-e", "PGID=1000",
        "-v", f"{library_volume}:/calibre-library",
        "-v", f"{ingest_volume}:/cwa-book-ingest",
        "crocodilestick/calibre-web-automated:latest"
    ], check=True, capture_output=True)
    
    print("   Waiting for container readiness...", end="", flush=True)
    start_time = time.time()
    calibre_ready = False
    ingest_ready = False
    max_wait = 60
    
    while (time.time() - start_time) < max_wait:
        result = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True)
        logs = result.stdout + result.stderr
        
        if "Calibre setup completed" in logs:
            calibre_ready = True
        if "STARTING CWA-INGEST SERVICE" in logs:
            ingest_ready = True
            
        if calibre_ready and ingest_ready:
            elapsed = time.time() - start_time
            print(f" ready in {elapsed:.1f}s ✅")
            break
            
        time.sleep(2)
    else:
        elapsed = time.time() - start_time
        print(f" timeout after {elapsed:.1f}s ⚠️")
    
    yield container_name
    
    print(f"\n🔵 Stopping container {container_name}")
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


@pytest.fixture(scope="session")
def ingest_folder_dind(test_volumes_dind):
    """Return VolumeHelper for the ingest volume."""
    ingest_volume, _ = test_volumes_dind
    return VolumeHelper(ingest_volume, "/cwa-book-ingest")


@pytest.fixture(scope="session")
def library_folder_dind(test_volumes_dind):
    """Return VolumeHelper for the library volume."""
    _, library_volume = test_volumes_dind
    return VolumeHelper(library_volume, "/calibre-library")
