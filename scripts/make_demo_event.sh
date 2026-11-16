#!/usr/bin/env bash
# Cree des evenements FICTIFS pour tester Rexo Studio sans images de clients :
#   - un mariage : 2 cartes memoire de rushes simulant une camera (plans
#     corrects, sombres, flous, trembles, surexposes, cache objectif, discours
#     en francais et en arabe par la synthese vocale de macOS), photos, musique ;
#   - un henne plus court.
# Les noms commencent par "TEST" et la fiche le precise : a supprimer a la main
# (glisser le dossier dans la Corbeille) quand on n'en a plus besoin.
#
# Usage : ./scripts/make_demo_event.sh            (racine : Evenements/ du projet)
#         REXO_EVENTS_DIR=/autre/racine ./scripts/make_demo_event.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FFMPEG="$ROOT/bin/ffmpeg"
[ -x "$FFMPEG" ] || FFMPEG="$(command -v ffmpeg)" || { echo "ffmpeg introuvable"; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ff() { "$FFMPEG" -hide_banner -loglevel error -y "$@"; }

# Cree l'evenement (dossiers + fiche) et affiche son chemin.
new_event() {  # type date noms lieu notes
  (cd "$ROOT" && python3 -c '
import sys
from montagia import config, events
print(events.create(config.EVENTS_DIR, *sys.argv[1:6])["path"])
' "$@")
}

VENC=(-c:v libx264 -preset veryfast -crf 24 -pix_fmt yuv420p -r 25)
AENC=(-c:a aac -b:a 128k -ar 48000 -ac 2)

# clip <sortie> <duree> <heure ISO> <filtre video> <source audio lavfi ou fichier>
clip() {
  local out="$1" dur="$2" when="$3" vf="$4" audio="$5"
  local ain=(-f lavfi -i "$audio")
  [ -f "$audio" ] && ain=(-i "$audio")
  ff -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=$dur" "${ain[@]}" \
     -filter_complex "[0:v]$vf[v]" -map "[v]" -map 1:a -t "$dur" \
     "${VENC[@]}" "${AENC[@]}" -metadata creation_time="$when" -movflags +faststart "$out"
  touch -t "$(date -j -f %Y-%m-%dT%H:%M:%SZ "$when" +%Y%m%d%H%M.%S)" "$out"
  echo "    $(basename "$out")  ${dur}s  ($vf)"
}

AMBI="anoisesrc=color=pink:amplitude=0.04:sample_rate=48000,aformat=channel_layouts=stereo"
MUSIC="aevalsrc='0.15*sin(2*PI*261.6*t)*(1+0.4*sin(2*PI*2*t))+0.12*sin(2*PI*329.6*t)+0.1*sin(2*PI*392*t)|0.15*sin(2*PI*261.6*t)+0.12*sin(2*PI*329.6*t)*(1+0.4*sin(2*PI*2*t))+0.1*sin(2*PI*392*t)':s=48000"
DARK="lutrgb=r=val*0.18:g=val*0.18:b=val*0.18,noise=alls=14:allf=t"   # basse lumiere
CAP="lutrgb=r=val*0.02:g=val*0.02:b=val*0.02,noise=alls=6:allf=t"     # cache objectif
BURN="lutrgb=r='min(255,val*0.4+175)':g='min(255,val*0.4+175)':b='min(255,val*0.4+175)'"  # surexpose
SHAKE="crop=1600:900:'160+120*sin(t*11)':'90+70*cos(t*15)',scale=1920:1080"

# Discours : voix macOS + ambiance de salle.
speech() {  # sortie.m4a voix texte
  say -v "$2" -o "$TMP/voice.aiff" "$3"
  ff -i "$TMP/voice.aiff" -f lavfi -i "$AMBI" \
     -filter_complex "[0:a]aresample=48000,aformat=channel_layouts=stereo,adelay=1500|1500,apad=pad_dur=2[s];[s][1:a]amix=inputs=2:duration=first:normalize=0[a]" \
     -map "[a]" "${AENC[@]}" "$1"
}

photo() {  # sortie heure_iso graine
  ff -f lavfi -i "testsrc2=size=3000x2000:rate=1,hue=h=$3*37:s=1.$(( $3 % 9 ))" -frames:v 1 \
     -q:v 3 "$1"
  touch -t "$(date -j -f %Y-%m-%dT%H:%M:%SZ "$2" +%Y%m%d%H%M.%S)" "$1"
}

echo "Rexo Studio - evenements fictifs de test"

# ---------------------------------------------------------------- mariage
EV="$(new_event Mariage 2026-11-14 "TEST Inès et Youssef" "Lieu fictif, Sousse" \
      "Événement fictif généré pour les tests : à supprimer")"
echo "  $EV"
C1="$EV/01_Rushes/Carte_1/PRIVATE/M4ROOT/CLIP"
C2="$EV/01_Rushes/Carte_2/PRIVATE/M4ROOT/CLIP"
mkdir -p "$C1" "$C2"

speech "$TMP/discours_fr.m4a" Thomas "Mesdames et messieurs, chers amis, bonsoir. Au nom des deux familles, merci d'être venus si nombreux ce soir. Inès et Youssef, nous vous souhaitons une vie pleine de joie, de patience et d'amour. Levons nos verres aux mariés !"
speech "$TMP/discours_ar.m4a" Maged "مبروك للعروسين، الله يتمم بالخير، وألف مبروك للعائلتين."

echo "  Carte 1"
clip "$C1/C0001.MP4" 18 2026-11-14T16:02:10Z "null"                             "$AMBI"
clip "$C1/C0002.MP4" 12 2026-11-14T16:10:45Z "$DARK"                            "$AMBI"
clip "$C1/C0003.MP4" 15 2026-11-14T16:25:03Z "gblur=sigma=14"                    "$AMBI"
clip "$C1/C0004.MP4" 20 2026-11-14T17:01:30Z "$SHAKE"                            "$MUSIC"
clip "$C1/C0005.MP4"  6 2026-11-14T17:05:12Z "$CAP"                             "$AMBI"
clip "$C1/C0006.MP4" 30 2026-11-14T19:40:00Z "null"                              "$TMP/discours_fr.m4a"
echo "  Carte 2"
clip "$C2/C0007.MP4" 14 2026-11-14T20:15:20Z "$BURN"                            "$MUSIC"
clip "$C2/C0008.MP4" 25 2026-11-14T20:30:00Z "null"                              "$MUSIC"
clip "$C2/C0009.MP4" 12 2026-11-14T21:02:40Z "null"                              "$TMP/discours_ar.m4a"
clip "$C2/C0010.MP4"  4 2026-11-14T21:10:05Z "null"                              "$AMBI"

echo "  Photos"
for i in $(seq 1 12); do
  photo "$EV/02_Photos/DSC_$(printf %04d "$i").JPG" "2026-11-14T$(printf %02d $((15 + i / 2))):$(printf %02d $((i * 4 % 60))):00Z" "$i"
done
echo "  Musique"
ff -f lavfi -i "$MUSIC" -t 60 "${AENC[@]}" "$EV/03_Audio/Musique_teaser_fictive.m4a"

# ---------------------------------------------------------------- henne
EV2="$(new_event Henne 2026-11-12 "TEST Inès" "Maison familiale fictive, Monastir" \
       "Événement fictif généré pour les tests : à supprimer")"
echo "  $EV2"
H1="$EV2/01_Rushes/Carte_1/DCIM/100MEDIA"
mkdir -p "$H1"
clip "$H1/DJI_0001.MP4" 16 2026-11-12T18:20:00Z "hue=h=40"   "$MUSIC"
clip "$H1/DJI_0002.MP4" 10 2026-11-12T18:45:00Z "$SHAKE"     "$AMBI"
for i in 1 2 3; do
  photo "$EV2/02_Photos/IMG_$(printf %04d "$i").JPG" "2026-11-12T18:3${i}:00Z" "$((i + 20))"
done

echo "Termine."
