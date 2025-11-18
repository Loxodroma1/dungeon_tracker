#!/usr/bin/env python3
"""
Dungeon Points Tracker - AUTOMATICKÉ SBÍRÁNÍ každé 2 hodiny
Stahuje data z Dark Paradise a zapisuje změny do CSV s názvem dungeonu
+ Denní vyhodnocení aktivních dungeonů
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import json
import csv
import time
from datetime import datetime, timedelta
from pathlib import Path
import re
import sys
import schedule
import os
from collections import defaultdict

class DungeonPointsTracker:
    def __init__(self, data_file="dungeon_data.json", csv_file="dungeon_changes.csv", 
                 dungeon_map_file="Dungeony2.csv"):
        self.url = "https://www.darkparadise.eu/dungeon-points"
        self.data_file = Path(data_file)
        self.csv_file = Path(csv_file)
        self.dungeon_map_file = Path(dungeon_map_file)
        
        # Detekce CI prostředí (GitHub Actions, atd.)
        self.is_ci = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'
        
        # Načti mapování dungeonů
        self.dungeon_map = self._load_dungeon_map()
        
        # Zkontroluj zda můžeš zapisovat do složky
        self._check_write_permissions()
        
        self.history = self._load_history()
        self._init_csv()
    
    def _load_dungeon_map(self):
        """Načte mapování bodů na dungeony z CSV"""
        dungeon_map = {}  # {body: [seznam dungeonů]}
        
        if not self.dungeon_map_file.exists():
            print(f"⚠️ VAROVÁNÍ: Soubor {self.dungeon_map_file} nenalezen!")
            print(f"   Vytvořte soubor Dungeony2.csv ve stejné složce jako skript.")
            return dungeon_map
        
        try:
            with open(self.dungeon_map_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    dungeon_name = row['Dung'].strip()
                    points_str = row['Dung body (plast)'].strip()
                    
                    if points_str:  # Pokud má hodnotu
                        try:
                            points = int(points_str)
                            if points not in dungeon_map:
                                dungeon_map[points] = []
                            dungeon_map[points].append(dungeon_name)
                        except ValueError:
                            continue
            
            print(f"✅ Načteno {len(dungeon_map)} různých bodových hodnot dungeonů")
            return dungeon_map
            
        except Exception as e:
            print(f"❌ Chyba při načítání {self.dungeon_map_file}: {e}")
            return dungeon_map
    
    def _get_dungeon_name(self, points):
        """Vrátí název dungeonu podle bodů"""
        if points not in self.dungeon_map:
            return f"Neznámý dungeon ({points} bodů)"
        
        dungeons = self.dungeon_map[points]
        if len(dungeons) == 1:
            return dungeons[0]
        else:
            # Více možností - vrátíme je oddělené " / "
            return " / ".join(dungeons)
    
    def _check_write_permissions(self):
        """Zkontroluje zda máme práva zápisu"""
        test_file = self.data_file.parent / ".write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            print(f"❌ CHYBA: Nemáte práva zápisu do složky: {self.data_file.parent}")
            print(f"💡 TIP: Přesuňte skript do jiné složky (např. Documents)")
            sys.exit(1)
    
    def _init_csv(self):
        """Inicializuje CSV soubor s hlavičkou"""
        if not self.csv_file.exists():
            try:
                with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Timestamp', 'Datum', 'Čas', 'Hráč', 
                                   'Body předtím', 'Body nyní', 'Změna', 'Dungeon'])
                print(f"✅ Vytvořen nový CSV soubor: {self.csv_file}")
            except PermissionError:
                print(f"❌ CHYBA: Nelze vytvořit CSV soubor: {self.csv_file}")
                print(f"   Zavřete Excel pokud máte soubor otevřený!")
                sys.exit(1)
    
    def _load_history(self):
        """Načte historii dat ze souboru"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, PermissionError) as e:
                print(f"⚠️ Varování: Nelze načíst historii z {self.data_file}: {e}")
                backup_file = self.data_file.with_suffix('.json.bak')
                try:
                    if self.data_file.exists():
                        self.data_file.rename(backup_file)
                        print(f"📦 Vadný soubor přejmenován na: {backup_file}")
                except Exception:
                    pass
                return []
        return []
    
    def _save_history(self):
        """Uloží historii dat do souboru"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                temp_file = self.data_file.with_suffix('.json.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.history, f, indent=2, ensure_ascii=False)
                
                if self.data_file.exists():
                    self.data_file.unlink()
                temp_file.rename(self.data_file)
                return
                
            except PermissionError as e:
                if attempt < max_attempts - 1:
                    print(f"⚠️ Pokus {attempt + 1}/{max_attempts}: Soubor zamčený, čekám 2s...")
                    time.sleep(2)
                else:
                    print(f"❌ CHYBA: Nelze uložit po {max_attempts} pokusech")
                    print(f"   Zavřete programy co mohou mít soubor otevřený!")
            except Exception as e:
                print(f"❌ Chyba při ukládání: {e}")
                break
    
    def _setup_driver(self):
        """Nastaví Selenium WebDriver"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        return webdriver.Chrome(options=chrome_options)
    
    def fetch_data(self, debug=False):
        """Stáhne aktuální data z webu"""
        driver = None
        try:
            driver = self._setup_driver()
            driver.get(self.url)
            time.sleep(5)
            
            if debug:
                with open('page_source.html', 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                driver.save_screenshot('page_screenshot.png')
                print("🔍 Debug: page_source.html a page_screenshot.png uloženy")
            
            page_text = driver.find_element(By.TAG_NAME, "body").text
            
            if debug:
                print(f"\n📄 Obsah stránky:\n{page_text[:500]}...\n")
            
            data = {}
            tables = driver.find_elements(By.TAG_NAME, "table")
            print(f"🔍 Nalezeno tabulek: {len(tables)}")
            
            if tables:
                for idx, table in enumerate(tables):
                    rows = table.find_elements(By.TAG_NAME, "tr")
                    print(f"🔍 Tabulka {idx+1}: {len(rows)} řádků")
                    
                    for row_idx, row in enumerate(rows):
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if not cells:
                            cells = row.find_elements(By.TAG_NAME, "th")
                        
                        if row_idx < 5 and debug:
                            cell_texts = [cell.text.strip() for cell in cells]
                            print(f"  Řádek {row_idx}: {cell_texts}")
                        
                        if len(cells) >= 3:
                            player = cells[1].text.strip()
                            points_text = cells[2].text.strip()
                            
                            cleaned_points = points_text.replace(' ', '').replace(',', '').replace('.', '')
                            points_match = re.search(r'\d+', cleaned_points)
                            if points_match and player and player.strip():
                                try:
                                    points_value = int(points_match.group())
                                    if points_value > 0:
                                        data[player] = points_value
                                        if len(data) <= 3:
                                            print(f"  ✅ {player} = {points_value}")
                                except ValueError:
                                    continue
            else:
                print("⚠️ Žádné tabulky, zkouším parsovat text...")
                lines = page_text.split('\n')
                
                for line in lines:
                    match = re.match(r'(.+?)\s+(\d+)\s*$', line.strip())
                    if match:
                        player = match.group(1).strip()
                        points = int(match.group(2))
                        if points > 100:
                            data[player] = points
                            if debug and len(data) <= 3:
                                print(f"  Parsováno: {player} = {points}")
            
            return data
        
        except Exception as e:
            print(f"❌ Chyba při stahování dat: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        finally:
            if driver:
                driver.quit()
    
    def calculate_diff(self, old_data, new_data):
        """Vypočítá rozdíly a určí dungeony"""
        if not old_data:
            return None
        
        diff = {}
        all_players = set(old_data.keys()) | set(new_data.keys())
        
        for player in all_players:
            old_points = old_data.get(player, 0)
            new_points = new_data.get(player, 0)
            change = new_points - old_points
            
            if change != 0:
                # Určení dungeonu podle změny bodů
                if change > 0:
                    dungeon = self._get_dungeon_name(change)
                else:
                    dungeon = "Ztráta bodů"
                
                diff[player] = {
                    'old': old_points,
                    'new': new_points,
                    'change': change,
                    'dungeon': dungeon
                }
        
        return diff
    
    def save_changes_to_csv(self, diff, timestamp):
        """Uloží změny do CSV s dungeonem"""
        if not diff:
            return
        
        date_str = timestamp.strftime('%Y-%m-%d')
        time_str = timestamp.strftime('%H:%M:%S')
        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                for player, changes in diff.items():
                    writer.writerow([
                        timestamp_str,
                        date_str,
                        time_str,
                        player,
                        changes['old'],
                        changes['new'],
                        changes['change'],
                        changes['dungeon']
                    ])
            
            print(f"💾 Změny uloženy do CSV ({len(diff)} hráčů)")
        except PermissionError:
            print(f"❌ CHYBA: Nelze zapsat do CSV - zavřete Excel!")
    
    def generate_daily_dungeon_report(self):
        """Vygeneruje denní report o aktivitě dungeonů"""
        if not self.csv_file.exists():
            print("⚠️ CSV soubor neexistuje, není co vyhodnocovat")
            return
        
        try:
            # Načti všechny záznamy z CSV
            dungeon_last_activity = {}  # {dungeon_name: (timestamp, count)}
            
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    dungeon = row['Dungeon'].strip()
                    timestamp_str = row['Timestamp'].strip()
                    change = int(row['Změna'])
                    
                    # Ignoruj ztráty bodů a neznámé dungeony
                    if change <= 0 or dungeon == "Ztráta bodů":
                        continue
                    
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        
                        # Aktualizuj poslední aktivitu dungeonu
                        if dungeon not in dungeon_last_activity:
                            dungeon_last_activity[dungeon] = {'timestamp': timestamp, 'count': 0}
                        
                        if timestamp > dungeon_last_activity[dungeon]['timestamp']:
                            dungeon_last_activity[dungeon]['timestamp'] = timestamp
                        
                        dungeon_last_activity[dungeon]['count'] += 1
                        
                    except ValueError:
                        continue
            
            # Vytiskni report
            now = datetime.now()
            print("\n" + "="*100)
            print(f"📊 DENNÍ VYHODNOCENÍ DUNGEONŮ - {now.strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*100)
            
            if not dungeon_last_activity:
                print("\n⚠️ Zatím nebyly zaznamenány žádné změny v dungeonech")
                print("="*100 + "\n")
                return
            
            # Seřaď podle poslední aktivity (od nejnovější)
            sorted_dungeons = sorted(
                dungeon_last_activity.items(),
                key=lambda x: x[1]['timestamp'],
                reverse=True
            )
            
            print(f"\n📋 Celkem sledováno dungeonů: {len(sorted_dungeons)}")
            print("\n" + "-"*100)
            print(f"{'DUNGEON':<40} {'POSLEDNÍ AKTIVITA':<25} {'PŘED':<20} {'POČET DOKONČENÍ':<15}")
            print("-"*100)
            
            for dungeon, info in sorted_dungeons:
                last_time = info['timestamp']
                count = info['count']
                time_ago = now - last_time
                
                # Formátuj "před X čas"
                if time_ago.days > 0:
                    time_ago_str = f"{time_ago.days} dny" if time_ago.days > 1 else "1 den"
                    if time_ago.days >= 7:
                        weeks = time_ago.days // 7
                        time_ago_str = f"{weeks} týdny" if weeks > 1 else "1 týden"
                else:
                    hours = time_ago.seconds // 3600
                    if hours > 0:
                        time_ago_str = f"{hours} hodin" if hours > 1 else "1 hodina"
                    else:
                        minutes = time_ago.seconds // 60
                        time_ago_str = f"{minutes} minut" if minutes > 1 else "1 minuta"
                
                # Ikona podle aktivity
                if time_ago.days == 0 and time_ago.seconds < 3600 * 6:  # méně než 6 hodin
                    icon = "🔥"  # velmi aktivní
                elif time_ago.days == 0:
                    icon = "✅"  # aktivní dnes
                elif time_ago.days <= 1:
                    icon = "🕐"  # včera
                elif time_ago.days <= 7:
                    icon = "📅"  # tento týden
                else:
                    icon = "❄️"  # neaktivní
                
                print(f"{icon} {dungeon:<38} {last_time.strftime('%Y-%m-%d %H:%M:%S'):<25} "
                      f"{time_ago_str:<20} {count:>15}x")
            
            print("-"*100)
            
            # Statistiky
            total_completions = sum(info['count'] for info in dungeon_last_activity.values())
            recent_24h = sum(1 for info in dungeon_last_activity.values() 
                           if (now - info['timestamp']).days == 0)
            recent_week = sum(1 for info in dungeon_last_activity.values() 
                            if (now - info['timestamp']).days <= 7)
            
            print(f"\n📈 STATISTIKY:")
            print(f"   Celkový počet dokončení: {total_completions}x")
            print(f"   Aktivní dungeonů dnes: {recent_24h}")
            print(f"   Aktivní dungeonů tento týden: {recent_week}")
            
            # Najdi nejvíce aktivní dungeon
            most_active = max(sorted_dungeons, key=lambda x: x[1]['count'])
            print(f"   Nejčastější dungeon: {most_active[0]} ({most_active[1]['count']}x)")
            
            print("\n" + "="*100 + "\n")
            
        except Exception as e:
            print(f"❌ Chyba při generování denního reportu: {e}")
            import traceback
            traceback.print_exc()
    
    def print_report(self, data, diff):
        """Vytiskne report s dungeony"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print("\n" + "="*80)
        print(f"🏰 DUNGEON POINTS REPORT - {timestamp}")
        print("="*80)
        
        if diff:
            print("\n📊 ZMĚNY OD POSLEDNÍ KONTROLY:")
            print("-"*80)
            
            sorted_diff = sorted(diff.items(), key=lambda x: x[1]['change'], reverse=True)
            
            for player, changes in sorted_diff:
                change = changes['change']
                dungeon = changes['dungeon']
                symbol = "📈" if change > 0 else "📉"
                sign = "+" if change > 0 else ""
                
                print(f"{symbol} {player:25} {changes['old']:>8} → {changes['new']:>8} "
                      f"({sign}{change:>3}) | {dungeon}")
            
            print("\n" + "-"*80)
            total_change = sum(d['change'] for d in diff.values())
            positive_changes = sum(1 for d in diff.values() if d['change'] > 0)
            negative_changes = sum(1 for d in diff.values() if d['change'] < 0)
            
            print(f"Celková změna: {total_change:+d} bodů")
            print(f"Hráčů s nárůstem: {positive_changes}")
            print(f"Hráčů s poklesem: {negative_changes}")
        else:
            print("\n✅ Žádné změny od poslední kontroly")
        
        print("\n📋 AKTUÁLNÍ STAV (TOP 10):")
        print("-"*80)
        
        sorted_data = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]
        for i, (player, points) in enumerate(sorted_data, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i:2}."
            print(f"{medal} {player:30} {points:>8} bodů")
        
        print("="*80 + "\n")
    
    def update(self, debug=False):
        """Hlavní funkce - stáhne data a vytvoří report"""
        print(f"\n⏳ [{datetime.now().strftime('%H:%M:%S')}] Stahuji data z {self.url}...")
        
        new_data = self.fetch_data(debug=debug)
        
        if new_data is None:
            print("❌ Stahování selhalo, zkusím to příště")
            return
        
        if not new_data:
            print("⚠️ Nebyly nalezeny žádné data")
            return
        
        print(f"✅ Načteno {len(new_data)} hráčů")
        
        old_data = self.history[-1]['data'] if self.history else {}
        diff = self.calculate_diff(old_data, new_data)
        
        timestamp = datetime.now()
        self.print_report(new_data, diff)
        
        if diff:
            self.save_changes_to_csv(diff, timestamp)
        
        self.history.append({
            'timestamp': timestamp.isoformat(),
            'data': new_data
        })
        
        self.history = self.history[-30:]
        self._save_history()
        
        print(f"💾 Data uložena (celkem {len(self.history)} záznamů v historii)")

def run_scheduled_update(tracker, debug=False):
    """Spustí aktualizaci a ošetří chyby"""
    try:
        tracker.update(debug=debug)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"\n❌ Chyba při automatické aktualizaci: {e}")
        import traceback
        traceback.print_exc()

def run_daily_report(tracker):
    """Spustí denní report a ošetří chyby"""
    try:
        tracker.generate_daily_dungeon_report()
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"\n❌ Chyba při generování denního reportu: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Hlavní funkce - automatické spouštění každé 2 hodiny + denní report"""
    debug = '--debug' in sys.argv
    manual = '--manual' in sys.argv
    daily_report_only = '--daily-report' in sys.argv
    
    # Detekce CI prostředí
    is_ci = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'
    
    tracker = DungeonPointsTracker()
    
    print("🚀 Dungeon Points Tracker - AUTOMATICKÉ SBÍRÁNÍ")
    print("="*80)
    if debug:
        print("🔍 DEBUG REŽIM AKTIVNÍ")
    if is_ci:
        print("🤖 Běží v CI prostředí (GitHub Actions)")
    print(f"📁 Složka: {Path.cwd()}")
    print(f"📄 JSON historie: dungeon_data.json")
    print(f"📊 CSV výstup: dungeon_changes.csv")
    print(f"🗺️ Mapa dungeonů: Dungeony2.csv")
    print(f"⏰ Interval: každé 2 hodiny")
    print(f"📅 Denní report: každých 24 hodin")
    print("="*80)
    
    # Pouze denní report
    if daily_report_only:
        print("\n📊 REŽIM DENNÍHO REPORTU")
        tracker.generate_daily_dungeon_report()
        print("\n✅ HOTOVO!")
        return
    
    if manual or is_ci:
        # Ruční režim nebo CI - spustí jednou a ukončí
        print("\n🔧 RUČNÍ REŽIM - Spuštění jednou")
        tracker.update(debug=debug)
        print("\n✅ HOTOVO!")
        return
    
    # Automatický režim
    print("\n🔄 AUTOMATICKÝ REŽIM - běží na pozadí")
    print("💡 Pro ukončení stiskněte Ctrl+C")
    print("\n" + "="*80)
    
    # První spuštění ihned
    print("\n🎯 Spouštím první kontrolu...")
    run_scheduled_update(tracker, debug)
    
    # První denní report ihned
    print("\n📊 Spouštím první denní report...")
    run_daily_report(tracker)
    
    # Naplánuj další spuštění každé 2 hodiny
    schedule.every(2).hours.do(run_scheduled_update, tracker, debug)
    
    # Naplánuj denní report každých 24 hodin
    schedule.every(24).hours.do(run_daily_report, tracker)
    
    next_run = datetime.now().replace(microsecond=0)
    next_run += timedelta(hours=2)
    next_daily = datetime.now().replace(microsecond=0)
    next_daily += timedelta(hours=24)
    
    print(f"\n⏰ Další kontrola naplánována na: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📅 Další denní report naplánován na: {next_daily.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Kontroluj každou minutu
            
    except KeyboardInterrupt:
        print("\n\n⛔ Ukončuji program...")
        print("✅ Data byla uložena")
        print("\nDěkuji za použití! 👋")

if __name__ == "__main__":
    main()
