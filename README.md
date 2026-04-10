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

## À faire
Modifier la fréquence de mise à jour (par défaut : 60 minutes).


## Mentions légales
Cette intégration n'est pas affiliée à la Régie de l'énergie du Québec ni au gouvernement du Québec. Elle extrait simplement les données publiques rendues disponibles sur leur carte interactive.
