# Régie Essence Québec pour Home Assistant

Une intégration personnalisée (Custom Component) pour Home Assistant qui récupère en temps réel les prix de l'essence au Québec. Les données proviennent directement de la base de données officielle (GeoJSON) de la [Régie de l'énergie du Québec](https://regieessencequebec.ca/).

## Fonctionnalités

- **100% Autonome :** Connexion directe aux serveurs gouvernementaux, sans API intermédiaire.
- **Support Multi-Carburants :** Remonte automatiquement les prix pour l'**Ordinaire**, le **Super** et le **Diesel** (lorsque disponibles à la station).
- **Regroupement par Appareil :** Les capteurs sont proprement regroupés sous un seul "Appareil" (Device) représentant votre station-service, incluant la bannière (Esso, Shell, etc.) et l'adresse.
- **Interface Utilisateur (Config Flow) :** Configuration facile via des menus déroulants (Région > Ville > Bannière > Station).

## Installation

### Méthode 1 : Via HACS (Recommandé)

[![Installer via HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=moimeme81&repository=essence-quebec-home-assistant&category=integration)

1. Ouvrez **HACS** dans votre instance Home Assistant.
2. Allez dans l'onglet **Intégrations**.
3. Cliquez sur les 3 petits points en haut à droite et sélectionnez **Dépôts personnalisés** (Custom repositories).
4. Ajoutez l'URL de ce dépôt GitHub (`https://github.com/moimeme81/essence-quebec-home-assistant`) et choisissez la catégorie **Intégration**.
5. Cliquez sur **Ajouter**, puis recherchez "Régie Essence Québec" dans HACS et cliquez sur **Télécharger**.
6. **Redémarrez Home Assistant**.

### Méthode 2 : Manuelle

1. Téléchargez le contenu de ce dépôt.
2. Copiez le dossier `custom_components/regie_essence_quebec` dans le dossier `custom_components` de votre configuration Home Assistant.
3. **Redémarrez Home Assistant**.

## Configuration

1. Dans Home Assistant, allez dans **Paramètres** > **Appareils et services**.
2. Cliquez sur le bouton **+ Ajouter une intégration** en bas à droite.
3. Recherchez **Régie Essence Québec**.
4. Suivez l'assistant de configuration :
   - Sélectionnez votre **Région**.
   - Sélectionnez votre **Ville**.
   - Sélectionnez la **Bannière** (ex: Shell, Couche-Tard).
   - Sélectionnez l'adresse exacte de la **Station**.
5. C'est fait ! Un nouvel appareil sera créé avec vos capteurs de prix.

## Exemple d'affichage sur le tableau de bord (Lovelace)

Vous pouvez afficher vos prix sous forme de liste classique avec la carte `entities` :

```yaml
type: entities
title: Prix de l'essence - Ma Station
icon: mdi:gas-station
state_color: true
entities:
  - entity: sensor.ma_station_ordinaire
    name: Ordinaire
    icon: mdi:gas-station
  - entity: sensor.ma_station_super
    name: Super
    icon: mdi:gas-station-outline
  - entity: sensor.ma_station_diesel
    name: Diesel
    icon: mdi:truck
```

## script de recherche de station la plus proche
À partir de la position d'un appareil sélectioné les 3 stations les plus proches sont retourné en notification actionable.

```yaml
alias: "Essence: Trouver les plus proches"
sequence:
  - data:
      latitude: "{{ state_attr('device_tracker.your_phone_here', 'latitude') }}"
      longitude: "{{ state_attr('device_tracker.your_phone_here', 'longitude') }}"
      limit: 3
    response_variable: gas_results
    action: regie_essence_quebec.find_closest_stations
  - data:
      title: ⛽ Top 3 Stations Proches
      message: >-
        {% for station in gas_results.stations %}  {{ loop.index }}. {{
        station.brand }} ({{ station.distance_km }} km) 📍 {{ station.Address }}
        {%- for price in station.Prices %} - {{ price.GasType }}: {{ price.Price
        }} {%- endfor %}

        {% endfor %}
      data:
        actions: >
          {% set limit = gas_results.stations | length %} {% set limit = 3 if
          limit > 3 else limit %} {% set ns = namespace(items=[]) %} {% for i in
          range(limit) %}
            {% set station = gas_results.stations[i] %}
            {% set short_brand = station.brand | truncate(6, true, '') %}
            {% set ns.items = ns.items + [
              {
                "action": "URI", 
                "title": "🚗 #" ~ (i + 1) ~ " " ~ short_brand, 
                "uri": "https://www.google.com/maps/search/?api=1&query=" ~ station.latitude ~ "," ~ station.longitude 
              }
            ] %}
          {% endfor %} {{ ns.items }}
    action: notify.mobile_app_YOUR_PHONE_HERE
mode: single
icon: mdi:gas-station

```

## À faire
- [x] ~~Rendre modifiable la fréquence de mise à jour (par défaut : 60 minutes).~~ Modifiable en cliquant sur l'icone de configuration de la station.
- [ ] ajouter les logo des marque


## Mentions légales
Cette intégration n'est pas affiliée à la Régie de l'énergie du Québec ni au gouvernement du Québec. Elle extrait simplement les données publiques rendues disponibles sur leur carte interactive.
