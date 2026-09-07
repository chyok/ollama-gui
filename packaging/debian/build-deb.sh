#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
output_dir=${1:-"$project_root/build/debian"}

for command_name in python3 dpkg-deb install sed; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required build command not found: %s\n' "$command_name" >&2
        exit 1
    fi
done

version=$(python3 -c \
    'import pathlib,re,sys; text=pathlib.Path(sys.argv[1]).read_text(); match=re.search(r"(?m)^version\s*=\s*\"([^\"]+)\"", text); print(match.group(1) if match else "")' \
    "$project_root/pyproject.toml" 2>/dev/null) || {
        printf 'Unable to read the project version from pyproject.toml\n' >&2
        exit 1
    }

case "$version" in
    ''|*[!0-9A-Za-z.+:~-]*)
        printf 'Invalid Debian package version: %s\n' "$version" >&2
        exit 1
        ;;
esac

staging_dir=$(mktemp -d "${TMPDIR:-/tmp}/ollama-speak-deb.XXXXXXXX")
trap 'rm -rf -- "$staging_dir"' EXIT HUP INT TERM

package_root="$staging_dir/ollama-speak_${version}_all"
mkdir -p \
    "$package_root/DEBIAN" \
    "$package_root/usr/bin" \
    "$package_root/usr/lib/python3/dist-packages" \
    "$package_root/usr/share/applications" \
    "$package_root/usr/share/doc/ollama-speak" \
    "$package_root/usr/share/icons/hicolor/scalable/apps" \
    "$package_root/usr/share/metainfo"

sed "s/@VERSION@/$version/g" \
    "$project_root/packaging/debian/control.in" \
    > "$package_root/DEBIAN/control"
chmod 0644 "$package_root/DEBIAN/control"

install -m 0644 "$project_root/ollama_speak.py" \
    "$package_root/usr/lib/python3/dist-packages/ollama_speak.py"
install -m 0755 "$project_root/packaging/debian/ollama-speak" \
    "$package_root/usr/bin/ollama-speak"
install -m 0644 \
    "$project_root/packaging/linux/io.github.drericflores.ollama-speak.desktop" \
    "$package_root/usr/share/applications/io.github.drericflores.ollama-speak.desktop"
install -m 0644 "$project_root/packaging/linux/ollama-speak.svg" \
    "$package_root/usr/share/icons/hicolor/scalable/apps/ollama-speak.svg"
install -m 0644 \
    "$project_root/packaging/linux/io.github.drericflores.ollama-speak.metainfo.xml" \
    "$package_root/usr/share/metainfo/io.github.drericflores.ollama-speak.metainfo.xml"
install -m 0644 "$project_root/README.md" \
    "$package_root/usr/share/doc/ollama-speak/README.md"
install -m 0644 "$project_root/INSTALL.md" \
    "$package_root/usr/share/doc/ollama-speak/INSTALL.md"
install -m 0644 "$project_root/packaging/debian/copyright" \
    "$package_root/usr/share/doc/ollama-speak/copyright"

find "$package_root" -type d -exec chmod 0755 {} +
mkdir -p "$output_dir"
package_path="$output_dir/ollama-speak_${version}_all.deb"
dpkg-deb --root-owner-group --build "$package_root" "$package_path"

printf '%s\n' "$package_path"
