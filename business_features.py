import json
from datetime import datetime, timezone, timedelta
import random
import discord
from discord import app_commands
from typing import Optional
import time
from shared_utils import calculate_level, calculate_gang_level, load_data, save_data
# Battle system imports moved to function level to avoid circular dependencies

class WarBattleActionView(discord.ui.View):
    def __init__(self, battle, current_player_id: str, data: dict):
        super().__init__(timeout=300)
        self.battle = battle
        self.current_player_id = current_player_id
        self.data = data

    @discord.ui.button(label="⚔️ Attack", style=discord.ButtonStyle.danger)
    async def attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_war_action(interaction, "attack")

    @discord.ui.button(label="💥 Heavy Attack", style=discord.ButtonStyle.danger)
    async def heavy_attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_war_action(interaction, "heavy_attack")

    @discord.ui.button(label="⚡ Quick Attack", style=discord.ButtonStyle.primary)
    async def quick_attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_war_action(interaction, "quick_attack")

    @discord.ui.button(label="🛡️ Defend", style=discord.ButtonStyle.secondary)  
    async def defend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_war_action(interaction, "defend")

    @discord.ui.button(label="😤 Intimidate", style=discord.ButtonStyle.secondary)
    async def intimidate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_war_action(interaction, "intimidate")

    @discord.ui.button(label="✨ Special", style=discord.ButtonStyle.success)
    async def special_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_war_action(interaction, "special")

    async def handle_war_action(self, interaction: discord.Interaction, action: str):
        user_id = str(interaction.user.id)

        # Check if it's the current player's turn
        current_player_id = self.battle.player1.user_id if self.battle.current_turn == 1 else self.battle.player2.user_id
        
        if user_id != current_player_id:
            # Get current player name for better error message
            try:
                current_user = interaction.client.get_user(int(current_player_id))
                current_name = current_user.display_name if current_user else f"Player {current_player_id[:8]}"
            except:
                current_name = f"Player {current_player_id[:8]}"
            
            turn_info = f"Turn {self.battle.turn_count + 1}: {current_name}"
            await interaction.response.send_message(f"❌ It's not your turn!\n🎯 **Current Turn:** {turn_info}", ephemeral=True)
            return

        # Execute the action
        result = self.battle.execute_action(action)

        if result.get("battle_end"):
            # Battle is over - award war-specific rewards
            await self.award_war_battle_rewards(interaction, result)

            # Remove from active battles
            from battle_system import active_battles
            battle_key = f"{self.battle.player1.user_id}_{self.battle.player2.user_id}"
            reverse_key = f"{self.battle.player2.user_id}_{self.battle.player1.user_id}"
            if battle_key in active_battles:
                del active_battles[battle_key]
            if reverse_key in active_battles:
                del active_battles[reverse_key]

            # Show final result
            if result["winner"] == "Draw":
                embed = discord.Embed(
                    title="🤝 **War Battle Draw!** 🤝",
                    description=result["message"],
                    color=0xFFFF00
                )
            else:
                embed = discord.Embed(
                    title=f"🏆 **{result['winner']} Wins the War Battle!** 🏆",
                    description=result["message"],
                    color=0x00FF00
                )

            await interaction.response.edit_message(embed=embed, view=None)
        else:
            # Show action result temporarily, then update to battle view
            action_embed = discord.Embed(
                title="⚔️ **War Battle Action** ⚔️",
                description=result["message"],
                color=0xFF6B6B if not result.get("hit", True) else 0x00FF00
            )

            # First, show the action result
            await interaction.response.edit_message(embed=action_embed, view=None)

            # Wait a moment, then show the updated battle state
            import asyncio
            await asyncio.sleep(2)

            # Continue battle
            from battle_system import create_battle_embed
            battle_embed = create_battle_embed(self.battle)
            battle_embed.title = "⚔️ **Gang War Battle** ⚔️"

            # Add war status
            if hasattr(self.battle, 'active_war') and self.battle.active_war:
                battle_embed.add_field(name="🎯 **War Status**", 
                                     value=f"Attacker: {self.battle.active_war.get('attacker_score', 0)}/100\nDefender: {self.battle.active_war.get('defender_score', 0)}/100", 
                                     inline=False)

            # Create new view for continued battle
            current_player = self.battle.get_current_player()
            new_view = WarBattleActionView(self.battle, current_player.user_id, self.data)

            await interaction.edit_original_response(embed=battle_embed, view=new_view)

    async def award_war_battle_rewards(self, interaction: discord.Interaction, result: dict):
        """Award XP, money and track user battles in war system"""
        gambling_data = self.data.get("gambling", {})

        # Track battle usage for both players
        for player in [self.battle.player1, self.battle.player2]:
            uid = player.user_id
            if uid not in gambling_data:
                gambling_data[uid] = {"dollars": 100, "xp": 0}

            # Determine if player is attacker or defender
            if hasattr(self.battle, 'active_war') and self.battle.active_war:
                user_business_data = get_user_business_data(uid, self.data)
                user_gang_id = user_business_data.get("gang_id")
                is_player_attacker = self.battle.active_war["attacker"] == user_gang_id

                # Update battle count
                if is_player_attacker:
                    if "attacker_members" not in self.battle.active_war:
                        self.battle.active_war["attacker_members"] = {}
                    current_battles = self.battle.active_war["attacker_members"].get(uid, self.battle.active_war.get("max_battles_per_user", 2))
                    self.battle.active_war["attacker_members"][uid] = max(0, current_battles - 1)
                else:
                    if "defender_members" not in self.battle.active_war:
                        self.battle.active_war["defender_members"] = {}
                    current_battles = self.battle.active_war["defender_members"].get(uid, self.battle.active_war.get("max_battles_per_user", 2))
                    self.battle.active_war["defender_members"][uid] = max(0, current_battles - 1)

            # Award rewards
            if result["winner"] == player.username:
                # Winner rewards
                xp_gain = 200 + (player.level * 20)
                money_gain = 100000 + (player.level * 10000)
                gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + xp_gain
                gambling_data[uid]["dollars"] = gambling_data[uid].get("dollars", 100) + money_gain
            elif result["winner"] != "Draw":
                # Loser consolation
                xp_gain = 100 + (player.level * 5)
                gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + xp_gain
            else:
                # Draw rewards
                xp_gain = 150 + (player.level * 10)
                money_gain = 50000 + (player.level * 5000)
                gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + xp_gain
                gambling_data[uid]["dollars"] = gambling_data[uid].get("dollars", 100) + money_gain

        # Check if war is over based on elimination system
        if hasattr(self.battle, 'active_war') and self.battle.active_war:
            gangs_data = self.data.get("gangs", {})
            attacker_gang = gangs_data.get(self.battle.active_war["attacker"], {})
            defender_gang = gangs_data.get(self.battle.active_war["defender"], {})

            total_attacker_members = len(attacker_gang.get("members", {}))
            total_defender_members = len(defender_gang.get("members", {}))

            # Count exhausted members
            attacker_exhausted = sum(1 for battles in self.battle.active_war.get("attacker_members", {}).values() if battles == 0)
            defender_exhausted = sum(1 for battles in self.battle.active_war.get("defender_members", {}).values() if battles == 0)

            # Check for war end conditions
            if attacker_exhausted >= total_attacker_members and defender_exhausted >= total_defender_members:
                self.battle.active_war["status"] = "completed"
                self.battle.active_war["winner"] = "draw"
            elif attacker_exhausted >= total_attacker_members:
                self.battle.active_war["status"] = "completed"
                self.battle.active_war["winner"] = self.battle.active_war["defender"]
            elif defender_exhausted >= total_defender_members:
                self.battle.active_war["status"] = "completed"
                self.battle.active_war["winner"] = self.battle.active_war["attacker"]

        save_business_data(self.data)

# Business Types and their properties
BUSINESS_TYPES = {
    "dispensary": {
        "name": "Cannabis Dispensary",
        "emoji": "🏪",
        "base_cost": 1000000,
        "base_income": 50000,
        "level_req": 25,
        "description": "Retail cannabis dispensary serving customers",
        "upgrade_cost_multiplier": 1.5,
        "max_level": 10
    },
    "grow_facility": {
        "name": "Growing Facility", 
        "emoji": "🏭",
        "base_cost": 2500000,
        "base_income": 100000,
        "level_req": 40,
        "description": "Large-scale cannabis cultivation facility",
        "upgrade_cost_multiplier": 1.8,
        "max_level": 8
    },
    "processing_lab": {
        "name": "Processing Laboratory",
        "emoji": "⚗️",
        "base_cost": 5000000,
        "base_income": 200000,
        "level_req": 60,
        "description": "Advanced processing and extraction facility",
        "upgrade_cost_multiplier": 2.0,
        "max_level": 6
    },
    "research_center": {
        "name": "Research Center",
        "emoji": "🔬",
        "base_cost": 10000000,
        "base_income": 350000,
        "level_req": 80,
        "description": "Cutting-edge cannabis research facility",
        "upgrade_cost_multiplier": 2.5,
        "max_level": 5
    }
}

# Gang System
GANG_ROLES = {
    "leader": {
        "name": "Gang Leader",
        "permissions": ["manage_members", "declare_war", "manage_territories", "upgrade_base"],
        "color": 0xFF0000
    },
    "officer": {
        "name": "Gang Officer", 
        "permissions": ["recruit_members", "manage_territories"],
        "color": 0xFFA500
    },
    "enforcer": {
        "name": "Gang Enforcer",
        "permissions": ["participate_wars"],
        "color": 0x800080
    },
    "member": {
        "name": "Gang Member",
        "permissions": ["participate_wars"],
        "color": 0x008000
    }
}

TERRITORY_TYPES = {
    "street_corner": {
        "name": "Street Corner",
        "emoji": "🚦",
        "cost": 500000,
        "income": 50000,
        "defense": 10,
        "description": "Basic street-level territory"
    },
    "neighborhood": {
        "name": "Neighborhood Block",
        "emoji": "🏘️", 
        "cost": 2000000,
        "income": 150000,
        "defense": 25,
        "description": "Control of a neighborhood block"
    },
    "district": {
        "name": "City District",
        "emoji": "🏙️",
        "cost": 10000000,
        "income": 500000,
        "defense": 50,
        "description": "Major city district control"
    },
    "port": {
        "name": "Import/Export Port",
        "emoji": "⚓",
        "cost": 25000000,
        "income": 1000000,
        "defense": 100,
        "description": "Strategic port for international trade"
    },
    "industrial_zone": {
        "name": "Industrial Zone",
        "emoji": "🏭",
        "cost": 50000000,
        "income": 2000000,
        "defense": 150,
        "description": "Large-scale industrial operations"
    },
    "financial_district": {
        "name": "Financial District",
        "emoji": "🏦",
        "cost": 100000000,
        "income": 4000000,
        "defense": 200,
        "description": "Heart of financial power"
    },
    "corporate_tower": {
        "name": "Corporate Tower",
        "emoji": "🏢",
        "cost": 250000000,
        "income": 8000000,
        "defense": 300,
        "description": "Ultimate symbol of corporate dominance"
    }
}

# Research Lab Projects
RESEARCH_PROJECTS = {
    "strain_genetics": {
        "name": "Advanced Strain Genetics",
        "cost": 5000000,
        "time_hours": 72,
        "level_req": 50,
        "benefits": {
            "growing_yield": 0.25,
            "strain_quality": 0.15
        },
        "description": "Research into genetic modification for superior strains"
    },
    "extraction_tech": {
        "name": "Extraction Technology",
        "cost": 8000000,
        "time_hours": 96,
        "level_req": 60,
        "benefits": {
            "processing_efficiency": 0.30,
            "product_purity": 0.20
        },
        "description": "Advanced extraction and purification methods"
    },
    "automation_systems": {
        "name": "Automation Systems",
        "cost": 15000000,
        "time_hours": 168,
        "level_req": 75,
        "benefits": {
            "business_efficiency": 0.40,
            "labor_costs": -0.25
        },
        "description": "Fully automated business operations"
    },
    "market_analysis": {
        "name": "Market Analysis AI",
        "cost": 12000000,
        "time_hours": 120,
        "level_req": 70,
        "benefits": {
            "market_prediction": 0.35,
            "demand_optimization": 0.20
        },
        "description": "AI-powered market analysis and prediction"
    }
}

# Achievement System
ACHIEVEMENTS = {
    # Business Achievements
    "first_business": {
        "name": "Entrepreneur",
        "description": "Purchase your first business",
        "emoji": "💼",
        "reward_money": 100000,
        "reward_xp": 1000
    },
    "business_empire": {
        "name": "Business Empire",
        "description": "Own 5 businesses simultaneously",
        "emoji": "🏢",
        "reward_money": 5000000,
        "reward_xp": 10000
    },
    "max_level_business": {
        "name": "Peak Performance",
        "description": "Upgrade a business to maximum level",
        "emoji": "⭐",
        "reward_money": 2000000,
        "reward_xp": 5000
    },

    # Gang Achievements
    "gang_founder": {
        "name": "Gang Founder",
        "description": "Create your first gang",
        "emoji": "👑",
        "reward_money": 500000,
        "reward_xp": 2000
    },
    "territory_controller": {
        "name": "Territory Controller",
        "description": "Control 3 territories simultaneously",
        "emoji": "🗺️",
        "reward_money": 3000000,
        "reward_xp": 7500
    },
    "war_veteran": {
        "name": "War Veteran",
        "description": "Win 10 gang wars",
        "emoji": "⚔",
        "reward_money": 10000000,
        "reward_xp": 15000
    },

    # Research Achievements
    "researcher": {
        "name": "Researcher",
        "description": "Complete your first research project",
        "emoji": "🔬",
        "reward_money": 1000000,
        "reward_xp": 3000
    },
    "innovation_master": {
        "name": "Innovation Master",
        "description": "Complete all research projects",
        "emoji": "🧠",
        "reward_money": 50000000,
        "reward_xp": 25000
    },

    # World Achievements
    "world_traveler": {
        "name": "World Traveler",
        "description": "Visit all 10 locations",
        "emoji": "✈️",
        "reward_money": 5000000,
        "reward_xp": 12000
    },
    "location_master": {
        "name": "Location Master",
        "description": "Establish businesses in 5 different locations",
        "emoji": "🌍",
        "reward_money": 25000000,
        "reward_xp": 20000
    }
}

# World Locations
WORLD_LOCATIONS = {
    "amsterdam": {
        "name": "Amsterdam, Netherlands",
        "emoji": "🇳🇱",
        "unlock_level": 20,
        "travel_cost": 100000,
        "business_multiplier": 1.2,
        "strain_bonus": ["Cheese", "White Widow"],
        "description": "Cannabis-friendly city with coffeeshops",
        "special_features": ["legal_dispensaries", "tourism_boost"]
    },
    "california": {
        "name": "California, USA", 
        "emoji": "🇺🇸",
        "unlock_level": 25,
        "travel_cost": 150000,
        "business_multiplier": 1.5,
        "strain_bonus": ["OG Kush", "Sour Diesel"],
        "description": "Legal cannabis state with huge market",
        "special_features": ["tech_innovation", "high_demand"]
    },
    "jamaica": {
        "name": "Jamaica",
        "emoji": "🇯🇲",
        "unlock_level": 30,
        "travel_cost": 80000,
        "business_multiplier": 0.8,
        "strain_bonus": ["Blue Dream", "Durban Poison"],
        "description": "Birthplace of ganja culture",
        "special_features": ["cultural_significance", "low_costs"]
    },
    "colombia": {
        "name": "Colombia",
        "emoji": "🇨🇴",
        "unlock_level": 35,
        "travel_cost": 120000,
        "business_multiplier": 1.0,
        "strain_bonus": ["Runtz", "Gelato"],
        "description": "Emerging legal cannabis market",
        "special_features": ["growing_climate", "export_potential"]
    },
    "canada": {
        "name": "Canada",
        "emoji": "🇨🇦",
        "unlock_level": 40,
        "travel_cost": 90000,
        "business_multiplier": 1.3,
        "strain_bonus": ["Wedding Cake", "Bruce Banner"],
        "description": "Fully legal recreational cannabis",
        "special_features": ["full_legalization", "corporate_friendly"]
    },
    "uruguay": {
        "name": "Uruguay",
        "emoji": "🇺🇾",
        "unlock_level": 45,
        "travel_cost": 200000,
        "business_multiplier": 0.9,
        "strain_bonus": ["Strawberry Cough", "Ghost Train Haze"],
        "description": "First country to fully legalize cannabis",
        "special_features": ["pioneer_status", "government_regulated"]
    },
    "thailand": {
        "name": "Thailand",
        "emoji": "🇹🇭",
        "unlock_level": 50,
        "travel_cost": 250000,
        "business_multiplier": 1.1,
        "strain_bonus": ["Dragon's Breath", "Unicorn Poop"],
        "description": "Recently legalized medical cannabis",
        "special_features": ["medical_focus", "tourism_potential"]
    },
    "south_africa": {
        "name": "South Africa",
        "emoji": "🇿🇦",
        "unlock_level": 55,
        "travel_cost": 180000,
        "business_multiplier": 0.7,
        "strain_bonus": ["Durban Poison", "Cheese"],
        "description": "Legal for personal use and cultivation",
        "special_features": ["cultivation_friendly", "low_competition"]
    },
    "switzerland": {
        "name": "Switzerland",
        "emoji": "🇨🇭",
        "unlock_level": 60,
        "travel_cost": 300000,
        "business_multiplier": 2.0,
        "strain_bonus": ["Godfather OG", "Gorilla Glue #4"],
        "description": "High-end CBD and research market",
        "special_features": ["premium_market", "research_focus"]
    },
    "space_station": {
        "name": "International Space Station",
        "emoji": "🚀",
        "unlock_level": 100,
        "travel_cost": 50000000,
        "business_multiplier": 10.0,
        "strain_bonus": ["Dragon's Breath", "Unicorn Poop"],
        "description": "The ultimate growing environment",
        "special_features": ["zero_gravity", "ultimate_prestige"]
    }
}

def missing_gang_war_error():
    """Handle missing gang war functionality"""
    return {
        "success": False,
        "error": "Gang war system not fully implemented"
    }

# load_data and save_data are now imported from shared_utils
load_business_data = load_data
save_business_data = save_data

def get_user_business_data(uid, data):
    """Get or initialize user's business data"""
    if "business" not in data:
        data["business"] = {}

    if uid not in data["business"]:
        data["business"][uid] = {
            "businesses": {},
            "total_income": 0,
            "gang_id": None,
            "gang_role": None,
            "current_location": "amsterdam",
            "visited_locations": ["amsterdam"],
            "achievements": [],
            "research_projects": {}
        }

    return data["business"][uid]

# calculate_gang_level and calculate_level are now imported from shared_utils

def load_equipment_data():
    """Load equipment data from battle_system"""
    try:
        from battle_system import load_equipment_data as battle_load_equipment
        return battle_load_equipment()
    except ImportError:
        # Fallback to local loading
        try:
            with open("contributions.json", "r") as f:
                data = json.load(f)
                if "equipment" not in data:
                    data["equipment"] = {}
                return data
        except FileNotFoundError:
            return {"equipment": {}}

def get_user_equipment(uid: str, data: dict) -> dict:
    """Get user's equipment loadout"""
    if "equipment" not in data:
        data["equipment"] = {}

    if uid not in data["equipment"]:
        data["equipment"][uid] = {
            "weapons": ["fists"],
            "clothing": ["street_clothes"],
            "current_weapon": "fists",
            "current_clothing": "street_clothes",
            "inventory": {}
        }

    return data["equipment"][uid]

def save_equipment_data(data):
    """Save equipment data"""
    with open("contributions.json", "w") as f:
        json.dump(data, f, indent=2)

def add_gang_xp(gang_id, xp_amount, data):
    """Add XP to a gang and handle level ups"""
    gangs_data = data.get("gangs", {})
    if gang_id not in gangs_data:
        return False

    gang_data = gangs_data[gang_id]
    old_xp = gang_data.get("gang_xp", 0)
    old_level = calculate_gang_level(old_xp)

    gang_data["gang_xp"] = old_xp + xp_amount
    new_level = calculate_gang_level(gang_data["gang_xp"])

    if new_level > old_level:
        gang_data["gang_level"] = new_level
        return True  # Level up occurred

    gang_data["gang_level"] = new_level
    return False

def get_territory_unlock_requirements():
    """Get territory unlock requirements based on gang level"""
    return {
        "street_corner": {"gang_level": 1, "cost": 500000},
        "neighborhood": {"gang_level": 5, "cost": 2000000},
        "district": {"gang_level": 15, "cost": 10000000},
        "port": {"gang_level": 30, "cost": 25000000},
        "industrial_zone": {"gang_level": 50, "cost": 50000000},
        "financial_district": {"gang_level": 75, "cost": 100000000},
        "corporate_tower": {"gang_level": 90, "cost": 250000000}
    }

def distribute_territory_income(gang_id, data):
    """Distribute territory income to all gang members"""
    gangs_data = data.get("gangs", {})
    if gang_id not in gangs_data:
        return 0

    gang_data = gangs_data[gang_id]
    territories = gang_data.get("territories", {})

    if not territories:
        return 0

    # Calculate total daily income
    total_income = 0

    for territory_id, territory_data in territories.items():
        territory_type = territory_data.get("type", "street_corner")
        if territory_type in TERRITORY_TYPES:
            total_income += TERRITORY_TYPES[territory_type]["income"]

    if total_income <= 0:
        return 0

    # Distribute to all gang members
    members = gang_data.get("members", {})
    member_count = len(members)

    if member_count == 0:
        return 0

    income_per_member = total_income // member_count
    gambling_data = data.get("gambling", {})

    for member_uid in members:
        if member_uid not in gambling_data:
            gambling_data[member_uid] = {"dollars": 100, "xp": 0}

        gambling_data[member_uid]["dollars"] = gambling_data[member_uid].get("dollars", 100) + income_per_member

    return income_per_member

async def show_enemy_member_selection(interaction, uid, user_level, war_data, target_gang_id, enemy_members, data):
    """Show selection menu for enemy gang members"""

    class EnemyMemberSelect(discord.ui.Select):
        def __init__(self):
            options = []
            gambling_data = data.get("gambling", {})

            for member_uid in enemy_members[:25]:  # Discord limit of 25 options
                try:
                    user = interaction.client.get_user(int(member_uid))
                    if user:
                        username = user.display_name
                    else:
                        username = f"User {member_uid[:8]}"
                except Exception:
                    username = f"User {member_uid[:8]}"

                # Get member's level
                member_gambling = gambling_data.get(member_uid, {"xp": 0})
                from smoke_features import calculate_level
                member_level = calculate_level(member_gambling.get("xp", 0))

                # Check if member has battles remaining
                if war_data.get("war_type") == "elimination":
                    max_battles = war_data.get("max_battles_per_user", 2)
                    user_gang_id = get_user_business_data(uid, data).get("gang_id")
                    is_attacker = war_data["attacker"] == user_gang_id

                    if is_attacker:
                        member_battles = war_data.get("defender_members", {}).get(member_uid, max_battles)
                    else:
                        member_battles = war_data.get("attacker_members", {}).get(member_uid, max_battles)

                    status = f"⚔️ {member_battles} battles left" if member_battles > 0 else "💀 Eliminated"
                else:
                    status = "⚔️ Available"

                options.append(
                    discord.SelectOption(
                        label=username,
                        description=f"Level {member_level} • {status}",
                        value=member_uid,
                        emoji="👤"
                    )
                )

            if not options:
                options.append(discord.SelectOption(
                    label="No available enemies",
                    description="All enemy members have been eliminated",
                    value="none"
                ))

            super().__init__(placeholder="Choose an enemy gang member to fight...", options=options)

        async def callback(self, select_interaction: discord.Interaction):
            if str(select_interaction.user.id) != uid:
                await select_interaction.response.send_message("❌ This isn't your battle menu!", ephemeral=True)
                return

            if self.values[0] == "none":
                await select_interaction.response.send_message("❌ No enemy members available!", ephemeral=True)
                return

            target_member_uid = self.values[0]

            # Check if target member has battles remaining (for elimination wars)
            if war_data.get("war_type") == "elimination":
                max_battles = war_data.get("max_battles_per_user", 2)
                user_gang_id = get_user_business_data(uid, data).get("gang_id")
                is_attacker = war_data["attacker"] == user_gang_id

                if is_attacker:
                    member_battles = war_data.get("defender_members", {}).get(target_member_uid, max_battles)
                else:
                    member_battles = war_data.get("attacker_members", {}).get(target_member_uid, max_battles)

                if member_battles <= 0:
                    await select_interaction.response.send_message("❌ This member has been eliminated!", ephemeral=True)
                    return

            # Start the battle with selected enemy
            await start_battle_with_selected_enemy(select_interaction, uid, user_level, war_data, target_gang_id, target_member_uid, data)

    embed = discord.Embed(
        title="🎯 **Select Enemy Gang Member** 🎯",
        description="*Choose which enemy gang member you want to fight*",
        color=0xFF0000
    )

    gangs_data = data.get("gangs", {})
    enemy_gang_data = gangs_data.get(target_gang_id)
    embed.add_field(name="👥 **Enemy Gang**", value=enemy_gang_data.get("name", "Unknown Gang"), inline=True)
    embed.add_field(name="⚔️ **Available Opponents**", value=f"{len(enemy_members)} members", inline=True)
    embed.add_field(name="💡 **War Type**", value=war_data.get("war_type", "elimination").title(), inline=True)

    view = discord.ui.View(timeout=300)
    view.add_item(EnemyMemberSelect())

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def start_war_battle_with_notification(interaction, uid, user_level, war_data, target_gang_id, data):
    """Start a war battle with enemy member selection"""
    gangs_data = data.get("gangs", {})
    enemy_gang_data = gangs_data.get(target_gang_id, {})
    enemy_members = list(enemy_gang_data.get("members", {}).keys())

    if not enemy_members:
        await interaction.response.send_message("❌ Enemy gang has no members!", ephemeral=True)
        return

    # Filter out eliminated members if using elimination war type
    if war_data.get("war_type") == "elimination":
        max_battles = war_data.get("max_battles_per_user", 2)
        user_gang_id = get_user_business_data(uid, data).get("gang_id")
        is_attacker = war_data["attacker"] == user_gang_id

        available_enemies = []
        for member_uid in enemy_members:
            if is_attacker:
                member_battles = war_data.get("defender_members", {}).get(member_uid, max_battles)
            else:
                member_battles = war_data.get("attacker_members", {}).get(member_uid, max_battles)
            
            if member_battles > 0:
                available_enemies.append(member_uid)

        if not available_enemies:
            await interaction.response.send_message("❌ All enemy members have been eliminated!", ephemeral=True)
            return

        enemy_members = available_enemies

    # Show enemy selection menu
    await show_enemy_member_selection(interaction, uid, user_level, war_data, target_gang_id, enemy_members, data)

async def start_battle_with_selected_enemy(interaction, uid, user_level, war_data, target_gang_id, target_member_uid, data):
    """Start battle with the selected enemy gang member"""
    try:
        from battle_system import BattlePlayer, StreetBattle, create_battle_embed, active_battles

        # Get user equipment using local functions
        equipment_data = load_equipment_data()
        user_equipment = get_user_equipment(uid, equipment_data)
        target_equipment = get_user_equipment(target_member_uid, equipment_data)

        # Enhanced username retrieval with multiple fallback methods
        target_user = interaction.client.get_user(int(target_member_uid))
        if target_user:
            target_username = target_user.display_name
        else:
            # Multiple fallback attempts for getting username
            gambling_data = data.get("gambling", {})
            target_gambling = gambling_data.get(target_member_uid, {})

            if "username" in target_gambling:
                target_username = target_gambling["username"]
            else:
                # Try players data
                players_data = data.get("players", {})
                if target_member_uid in players_data and "username" in players_data[target_member_uid]:
                    target_username = players_data[target_member_uid]["username"]
                else:
                    # Try to get user from Discord client with member list
                    try:
                        # Search through all guilds the bot is in
                        for guild in interaction.client.guilds:
                            member = guild.get_member(int(target_member_uid))
                            if member:
                                target_username = member.display_name
                                break
                        else:
                            # Final fallback with gang context
                            gangs_data = data.get("gangs", {})
                            enemy_gang_data = gangs_data.get(target_gang_id, {})
                            gang_name = enemy_gang_data.get('name', 'Enemy Gang')
                            target_username = f"{gang_name} Member"
                    except Exception:
                        # Ultimate fallback
                        gangs_data = data.get("gangs", {})
                        enemy_gang_data = gangs_data.get(target_gang_id, {})
                        gang_name = enemy_gang_data.get('name', 'Enemy Gang')
                        target_username = f"{gang_name} Fighter"

        # Get target user level
        gambling_data = data.get("gambling", {})
        target_gambling = gambling_data.get(target_member_uid, {"xp": 0})
        from smoke_features import calculate_level
        target_level = calculate_level(target_gambling.get("xp", 0))

        # Create battle players
        player1 = BattlePlayer(
            uid, 
            interaction.user.display_name, 
            user_level,
            user_equipment.get("current_weapon", "fists"),
            user_equipment.get("current_clothing", "street_clothes")
        )

        player2 = BattlePlayer(
            target_member_uid,
            target_username,
            target_level,
            target_equipment.get("current_weapon", "fists"),
            target_equipment.get("current_clothing", "street_clothes")
        )

        # Create battle with proper war context
        battle = StreetBattle(player1, player2, "gang_war")
        battle.active_war = war_data
        user_gang_id = get_user_business_data(uid, data).get("gang_id")
        battle.is_attacker = war_data["attacker"] == user_gang_id
        battle.war_gang_id = user_gang_id
        battle.enemy_gang_id = target_gang_id

        # Ensure both players have proper user IDs as strings and set battle context
        battle.player1.user_id = str(battle.player1.user_id)
        battle.player2.user_id = str(battle.player2.user_id)

        # Set the current turn to the initiating player (player1)
        battle.current_turn = 1

        # Store battle with both possible keys for proper lookup
        battle_key = f"{uid}_{target_member_uid}"
        reverse_key = f"{target_member_uid}_{uid}"
        active_battles[battle_key] = battle
        active_battles[reverse_key] = battle

        # Notify the target user
        if target_user:
            try:
                gangs_data = data.get("gangs", {})
                user_gang_data = gangs_data.get(user_gang_id, {})

                notify_embed = discord.Embed(
                    title="⚔️ **YOU'RE BEING CHALLENGED TO BATTLE!** ⚔️",
                    description=f"*{interaction.user.mention} from {user_gang_data.get('name', 'Unknown Gang')} has challenged you to gang war combat!*",
                    color=0xFF6600
                )
                notify_embed.add_field(name="🥊 **Challenger**", value=f"{interaction.user.mention}\nLevel {user_level}", inline=True)
                notify_embed.add_field(name="🛡️ **Your Gang**", value=gangs_data.get(target_gang_id, {}).get('name', 'Unknown'), inline=True)
                notify_embed.add_field(name="⚔️ **Battle Type**", value="Gang War Battle", inline=True)
                notify_embed.set_footer(text="This is a real gang war battle! Fight back when it's your turn!")

                await target_user.send(embed=notify_embed)
            except Exception as e:
                print(f"Could not notify target user: {e}")

        # Create battle embed and view
        embed = create_battle_embed(battle)
        embed.title = "⚔️ **Gang War Battle** ⚔️"
        embed.description = f"*{interaction.user.display_name} vs {target_username}*"
        embed.add_field(name="🎯 **War Context**", 
                       value=f"Attacker: {war_data.get('attacker_score', 0)}/100\nDefender: {war_data.get('defender_score', 0)}/100", 
                       inline=False)

        # Create custom view for war battles
        view = WarBattleActionView(battle, uid, data)

        await interaction.response.send_message(embed=embed, view=view)

    except ImportError:
        await interaction.response.send_message("❌ Battle system not available!", ephemeral=True)
        return

def calculate_business_income(business_data, location_multiplier=1.0):
    """Calculate total income from all businesses"""
    total_income = 0
    for business_id, business in business_data.get("businesses", {}).items():
        business_type = BUSINESS_TYPES[business["type"]]
        level_multiplier = 1 + (business["level"] - 1) * 0.3
        base_income = business_type["base_income"]

        # Apply research bonuses
        research_bonus = 1.0
        for project_id, project in business_data.get("research_projects", {}).items():
            if project.get("completed"):
                project_info = RESEARCH_PROJECTS[project_id]
                if "business_efficiency" in project_info["benefits"]:
                    research_bonus += project_info["benefits"]["business_efficiency"]

        business_income = int(base_income * level_multiplier * location_multiplier * research_bonus)
        total_income += business_income

    return total_income

def check_achievement(uid, achievement_id, user_data, business_data):
    """Check if user has earned an achievement"""
    if achievement_id in user_data.get("achievements", []):
        return False

    earned = False

    # Check achievement conditions
    if achievement_id == "first_business":
        earned = len(business_data.get("businesses", {})) >= 1
    elif achievement_id == "business_empire":
        earned = len(business_data.get("businesses", {})) >= 5
    elif achievement_id == "max_level_business":
        for business in business_data.get("businesses", {}).values():
            business_type = BUSINESS_TYPES[business["type"]]
            if business["level"] >= business_type["max_level"]:
                earned = True
                break
    elif achievement_id == "gang_founder":
        earned = business_data.get("gang_role") == "leader"
    elif achievement_id == "world_traveler":
        earned = len(business_data.get("visited_locations", [])) >= 10

    return earned

def apply_achievement_rewards(uid, achievement_id, data):
    """Apply achievement rewards to user"""
    achievement = ACHIEVEMENTS[achievement_id]
    gambling_data = data.get("gambling", {})

    if uid not in gambling_data:
        gambling_data[uid] = {"dollars": 100, "xp": 0}

    # Apply money reward
    gambling_data[uid]["dollars"] = gambling_data[uid].get("dollars", 100) + achievement["reward_money"]

    # Apply XP reward
    gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + achievement["reward_xp"]

    # Add achievement to user's list
    business_data = get_user_business_data(uid, data)
    if "achievements" not in business_data:
        business_data["achievements"] = []
    business_data["achievements"].append(achievement_id)

# Create the business command group
business_group = app_commands.Group(name="business", description="Business management and empire building")

@business_group.command(name="status", description="View your business empire status")
async def business_status(interaction: discord.Interaction):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    # Get current location
    current_location = user_business_data.get("current_location", "amsterdam")
    location_info = WORLD_LOCATIONS[current_location]

    embed = discord.Embed(
        title="🏢 **Your Business Empire** 🏢",
        description=f"*{interaction.user.mention}'s business operations*",
        color=0x32CD32
    )

    # Location info
    embed.add_field(
        name=f"{location_info['emoji']} **Current Location**",
        value=f"{location_info['name']}\n*{location_info['description']}*",
        inline=True
    )

    # Business overview
    businesses = user_business_data.get("businesses", {})
    if businesses:
        business_list = []
        total_income = 0
        for business_id, business in businesses.items():
            business_type = BUSINESS_TYPES[business["type"]]
            level_multiplier = 1 + (business["level"] - 1) * 0.3
            income = int(business_type["base_income"] * level_multiplier * location_info["business_multiplier"])
            total_income += income
            business_list.append(f"{business_type['emoji']} **{business_type['name']}** (Lv.{business['level']}) - ${income:,}/hr")

        embed.add_field(
            name="🏢 **Your Businesses**",
            value="\n".join(business_list[:5]) + (f"\n*+{len(business_list)-5} more...*" if len(business_list) > 5 else ""),
            inline=False
        )

        embed.add_field(name="💰 **Total Income**", value=f"`${total_income:,}/hour`", inline=True)
    else:
        embed.add_field(
            name="🏢 **Your Businesses**",
            value="*No businesses owned. Use `/business buy` to start!*",
            inline=False
        )

    # Gang info
    gang_id = user_business_data.get("gang_id")
    if gang_id:
        gang_data = data.get("gangs", {}).get(gang_id, {})
        gang_role = user_business_data.get("gang_role", "member")
        role_info = GANG_ROLES[gang_role]
        embed.add_field(
            name="👥 **Gang Affiliation**",
            value=f"**{gang_data.get('name', 'Unknown')}**\nRole: {role_info['name']}",
            inline=True
        )

    # Achievements
    achievements_count = len(user_business_data.get("achievements", []))
    embed.add_field(name="🏆 **Achievements**", value=f"`{achievements_count}/{len(ACHIEVEMENTS)}`", inline=True)

    embed.set_footer(text="🌍 Build your empire across the globe!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@business_group.command(name="buy", description="Purchase a new business")
async def business_buy(interaction: discord.Interaction):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    # Get user level and balance
    gambling_data = data.get("gambling", {})
    user_gambling = gambling_data.get(uid, {"dollars": 100, "xp": 0})
    current_balance = user_gambling.get("dollars", 100)

    from smoke_features import calculate_level
    user_level = calculate_level(user_gambling.get("xp", 0))

    # Get current location multiplier
    current_location = user_business_data.get("current_location", "amsterdam")
    location_info = WORLD_LOCATIONS[current_location]

    class BusinessSelect(discord.ui.Select):
        def __init__(self):
            options = []
            existing_businesses = user_business_data.get("businesses", {})
            owned_types = [biz["type"] for biz in existing_businesses.values()]

            for business_type, business_info in BUSINESS_TYPES.items():
                if user_level >= business_info["level_req"]:
                    cost = int(business_info["base_cost"] * location_info["business_multiplier"])

                    if business_type in owned_types:
                        status = "👑 OWNED"
                    elif cost <= current_balance:
                        status = "✅"
                    else:
                        status = "❌"

                    options.append(
                        discord.SelectOption(
                            label=business_info["name"],
                            description=f"${cost:,} {status} - {business_info['description'][:30]}...",
                            value=business_type,
                            emoji=business_info["emoji"]
                        )
                    )

            if not options:
                options.append(discord.SelectOption(
                    label="No businesses available",
                    description="Level up to unlock more businesses!",
                    value="none"
                ))

            super().__init__(placeholder="Choose a business to purchase...", options=options)

        async def callback(self, interaction: discord.Interaction):
            if str(interaction.user.id) != uid:
                await interaction.response.send_message("❌ This isn't your business menu!", ephemeral=True)
                return

            if self.values[0] == "none":
                await interaction.response.send_message("❌ No businesses available at your level!", ephemeral=True)
                return

            business_type = self.values[0]
            business_info = BUSINESS_TYPES[business_type]

            # Check if user already owns this business type
            existing_businesses = user_business_data.get("businesses", {})
            for existing_business in existing_businesses.values():
                if existing_business["type"] == business_type:
                    await interaction.response.send_message(
                        f"❌ You already own a {business_info['name']}! You can only own one of each business type.",
                        ephemeral=True)
                    return

            cost = int(business_info["base_cost"] * location_info["business_multiplier"])

            if current_balance < cost:
                await interaction.response.send_message(
                    f"❌ You need ${cost:,} but only have ${current_balance:,}!",
                    ephemeral=True)
                return

            # Purchase business
            user_gambling["dollars"] -= cost

            # Generate business ID

            business_id = f"business_{int(time.time() * 1000)}"

            user_business_data["businesses"][business_id] = {
                "type": business_type,
                "level": 1,
                "location": current_location,
                "purchased_at": datetime.now(timezone.utc).isoformat()
            }

            save_business_data(data)

            # Check for achievements
            achievement_text = ""
            if check_achievement(uid, "first_business", user_business_data, user_business_data):
                apply_achievement_rewards(uid, "first_business", data)
                save_business_data(data)
                achievement_text = "\n🏆 **Achievement Unlocked: Entrepreneur!**"

            embed = discord.Embed(
                title="🏢 **Business Purchased!** 🏢",
                description=f"*You bought {business_info['name']} in {location_info['name']}!*",
                color=0x32CD32
            )
            embed.add_field(name="🏢 **Business**", value=business_info["name"], inline=True)
            embed.add_field(name="💰 **Cost**", value=f"`${cost:,}`", inline=True)
            embed.add_field(name="💵 **Remaining**", value=f"`${user_gambling['dollars']:,}`", inline=True)
            embed.add_field(name="📈 **Income**", value=f"`${business_info['base_income']:,}/hour`", inline=True)
            embed.add_field(name="📍 **Location**", value=location_info['name'], inline=True)
            embed.set_footer(text="🌟 Your business empire grows!" + achievement_text)

            await interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="🛒 **Business Marketplace** 🛒",
        description=f"*Purchase businesses in {location_info['name']}*",
        color=0x32CD32
    )
    embed.add_field(name="💰 **Your Balance**", value=f"`${current_balance:,}`", inline=True)
    embed.add_field(name="🏆 **Your Level**", value=f"`{user_level}`", inline=True)
    embed.add_field(name="📍 **Location**", value=location_info['name'], inline=True)
    embed.add_field(name="📈 **Location Multiplier**", value=f"`{location_info['business_multiplier']}x`", inline=True)

    view = discord.ui.View(timeout=300)
    view.add_item(BusinessSelect())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# Create gang command group
gang_group = app_commands.Group(name="gang", description="Gang management and warfare system")

@gang_group.command(name="create", description="Create a new gang")
@app_commands.describe(name="Name of your gang", description="Gang description")
async def gang_create(interaction: discord.Interaction, name: str, description: str = "A powerful gang"):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    # Check if user is already in a gang
    if user_business_data.get("gang_id"):
        await interaction.response.send_message("❌ You're already in a gang! Leave first with `/gang leave`.", ephemeral=True)
        return

    # Check if gang name already exists
    gangs_data = data.get("gangs", {})
    for gang_id, gang_data in gangs_data.items():
        if gang_data.get("name", "").lower() == name.lower():
            await interaction.response.send_message("❌ A gang with that name already exists!", ephemeral=True)
            return

    # Check cost
    gang_cost = 1000000
    gambling_data = data.get("gambling", {})
    user_gambling = gambling_data.get(uid, {"dollars": 100})

    if user_gambling.get("dollars", 100) < gang_cost:
        await interaction.response.send_message(f"❌ Creating a gang costs ${gang_cost:,}!", ephemeral=True)
        return

    # Create gang

    gang_id = f"gang_{int(time.time() * 1000)}"

    gangs_data[gang_id] = {
        "name": name,
        "description": description,
        "leader": uid,
        "members": {uid: "leader"},
        "territories": {},
        "wars": {},
        "founded_at": datetime.now(timezone.utc).isoformat(),
        "base_level": 1,
        "treasury": 0,
        "gang_xp": 0,
        "gang_level": 1
    }

    # Update user data
    user_gambling["dollars"] -= gang_cost
    user_business_data["gang_id"] = gang_id
    user_business_data["gang_role"] = "leader"

    save_business_data(data)

    # Sync to cross-server network
    try:
        from cross_server_features import sync_gang_cross_server
        server_id = str(interaction.guild.id) if interaction.guild else "0"
        sync_gang_cross_server(gang_id, gangs_data[gang_id], server_id)
    except Exception as e:
        print(f"Cross-server gang sync error: {e}")

    # Check achievement
    achievement_text = ""
    if check_achievement(uid, "gang_founder", user_business_data, user_business_data):
        apply_achievement_rewards(uid, "gang_founder", data)
        save_business_data(data)
        achievement_text = "\n🏆 **Achievement Unlocked: Gang Founder!**"

    embed = discord.Embed(
        title="👑 **Gang Created!** 👑",
        description=f"*{interaction.user.mention} founded the {name} gang!*",
        color=0xFF0000
    )
    embed.add_field(name="👥 **Gang Name**", value=name, inline=True)
    embed.add_field(name="👑 **Leader**", value=interaction.user.mention, inline=True)
    embed.add_field(name="💰 **Cost**", value=f"`${gang_cost:,}`", inline=True)
    embed.add_field(name="📝 **Description**", value=description, inline=False)
    embed.set_footer(text="Use /gang invite to recruit members!" + achievement_text)

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="info", description="View gang information and members")
async def gang_info(interaction: discord.Interaction):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang! Create one with `/gang create` or wait for an invite.", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    if not gang_data:
        await interaction.response.send_message("❌ Gang not found!", ephemeral=True)
        return

    # Get member count and roles
    members = gang_data.get("members", {})
    member_list = []

    for member_uid, role in members.items():
        try:
            user = interaction.client.get_user(int(member_uid))
            if user:
                username = getattr(user, 'display_name', user.name)
            else:
                username = f"User {member_uid}"
            role_info = GANG_ROLES.get(role, {"name": role})
            member_list.append(f"• {username} ({role_info['name']})")
        except Exception:
            member_list.append(f"• User {member_uid} ({role})")

    embed = discord.Embed(
        title=f"👥 **{gang_data['name']}** 👥",
        description=gang_data.get("description", "No description"),
        color=0xFF0000
    )

    embed.add_field(name="👑 **Leader**", 
                    value=f"<@{gang_data['leader']}>", inline=True)
    embed.add_field(name="👥 **Members**", 
                    value=f"`{len(members)}`", inline=True)
    embed.add_field(name="🏰 **Gang Level**", 
                    value=f"`{gang_data.get('gang_level', 1)}`", inline=True)
    embed.add_field(name="⭐ **Gang XP**", 
                    value=f"`{gang_data.get('gang_xp', 0):,}`", inline=True)
    embed.add_field(name="💰 **Treasury**", 
                    value=f"`${gang_data.get('treasury', 0):,}`", inline=True)
    embed.add_field(name="🗓️ **Founded**", 
                    value=f"<t:{int(datetime.fromisoformat(gang_data['founded_at']).timestamp())}:R>", inline=True)

    if member_list:
        embed.add_field(name="👥 **Member List**", 
                        value="\n".join(member_list[:10]) + (f"\n*+{len(member_list)-10} more...*" if len(member_list) > 10 else ""), 
                        inline=False)

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="invite", description="Invite a player to your gang")
@app_commands.describe(user="User to invite to the gang")
async def gang_invite(interaction: discord.Interaction, user: discord.Member):
    data = load_business_data()
    uid = str(interaction.user.id)
    target_uid = str(user.id)

    user_business_data = get_user_business_data(uid, data)
    target_business_data = get_user_business_data(target_uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    # Check permissions
    user_role = user_business_data.get("gang_role")
    if user_role not in ["leader", "officer"]:
        await interaction.response.send_message("❌ Only gang leaders and officers can invite members!", ephemeral=True)
        return

    # Check if target is already in a gang
    if target_business_data.get("gang_id"):
        await interaction.response.send_message("❌ That user is already in a gang!", ephemeral=True)
        return

    class InviteView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
        async def accept_invite(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != user.id:
                await button_interaction.response.send_message("❌ This invitation isn't for you!", ephemeral=True)
                return

            # Add to gang
            gang_data["members"][target_uid] = "member"
            target_business_data["gang_id"] = gang_id
            target_business_data["gang_role"] = "member"

            save_business_data(data)

            embed = discord.Embed(
                title="✅ **Gang Invitation Accepted!** ✅",
                description=f"*{user.mention} joined {gang_data['name']}!*",
                color=0x00FF00
            )
            await button_interaction.response.edit_message(embed=embed, view=None)

        @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
        async def decline_invite(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != user.id:
                await button_interaction.response.send_message("❌ This invitation isn't for you!", ephemeral=True)
                return

            embed = discord.Embed(
                title="❌ **Gang Invitation Declined** ❌",
                description=f"*{user.mention} declined the invitation to {gang_data['name']}*",
                color=0xFF0000
            )
            await button_interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="📨 **Gang Invitation** 📨",
        description=f"*{interaction.user.mention} invites {user.mention} to join **{gang_data['name']}**!*",
        color=0xFFFF00
    )
    embed.add_field(name="👥 **Gang**", value=gang_data['name'], inline=True)
    embed.add_field(name="📝 **Description**", value=gang_data.get('description', 'No description'), inline=False)

    await interaction.response.send_message(embed=embed, view=InviteView())

@gang_group.command(name="leave", description="Leave your current gang")
async def gang_leave(interaction: discord.Interaction):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    # Check if user is the leader
    if gang_data and gang_data.get("leader") == uid:
        # Transfer leadership or disband
        members = gang_data.get("members", {})
        other_members = [m for m in members.keys() if m != uid]

        if other_members:
            # Transfer to first officer, or first member
            new_leader = None
            for member_uid in other_members:
                if members[member_uid] == "officer":
                    new_leader = member_uid
                    break
            if not new_leader:
                new_leader = other_members[0]

            gang_data["leader"] = new_leader
            gang_data["members"][new_leader] = "leader"

            embed = discord.Embed(
                title="👑 **Leadership Transferred** 👑",
                description=f"*{interaction.user.mention} left the gang. Leadership transferred to <@{new_leader}>*",
                color=0xFFFF00
            )
        else:
            # Disband gang
            del gangs_data[gang_id]
            embed = discord.Embed(
                title="💥 **Gang Disbanded** 💥",
                description=f"*{gang_data['name']} has been disbanded as the last member left*",
                color=0xFF0000
            )
    else:
        embed = discord.Embed(
            title="👋 **Left Gang** 👋",
            description=f"*{interaction.user.mention} left {gang_data['name']}*",
            color=0xFF6B6B
        )

    # Remove user from gang
    if gang_id in gangs_data and uid in gangs_data[gang_id].get("members", {}):
        del gangs_data[gang_id]["members"][uid]

    user_business_data["gang_id"] = None
    user_business_data["gang_role"] = None

    save_business_data(data)
    await interaction.response.send_message(embed=embed)

@gang_group.command(name="kick", description="Kick a member from your gang")
@app_commands.describe(user="User to kick from the gang")
async def gang_kick(interaction: discord.Interaction, user: discord.Member):
    data = load_business_data()
    uid = str(interaction.user.id)
    target_uid = str(user.id)

    user_business_data = get_user_business_data(uid, data)
    target_business_data = get_user_business_data(target_uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    # Check permissions
    user_role = user_business_data.get("gang_role")

    if user_role != "leader":
        await interaction.response.send_message("❌ Only the gang leader can kick members!", ephemeral=True)
        return

    if target_business_data.get("gang_id") != gang_id:
        await interaction.response.send_message("❌ That user is not in your gang!", ephemeral=True)
        return

    if target_uid == uid:
        await interaction.response.send_message("❌ You can't kick yourself! Use `/gang leave` instead.", ephemeral=True)
        return

    # Remove from gang
    if target_uid in gang_data.get("members", {}):
        del gang_data["members"][target_uid]

    target_business_data["gang_id"] = None
    target_business_data["gang_role"] = None

    save_business_data(data)

    embed = discord.Embed(
        title="👢 **Member Kicked** 👢",
        description=f"*{user.mention} was kicked from {gang_data['name']} by {interaction.user.mention}*",
        color=0xFF0000
    )

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="promote", description="Promote a gang member")
@app_commands.describe(user="User to promote", role="New role for the user")
@app_commands.choices(role=[
    app_commands.Choice(name="Officer", value="officer"),
    app_commands.Choice(name="Enforcer", value="enforcer"),
    app_commands.Choice(name="Member", value="member")
])
async def gang_promote(interaction: discord.Interaction, user: discord.Member, role: str):
    data = load_business_data()
    uid = str(interaction.user.id)
    target_uid = str(user.id)

    user_business_data = get_user_business_data(uid, data)
    target_business_data = get_user_business_data(target_uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    # Check permissions
    if user_business_data.get("gang_role") != "leader":
        await interaction.response.send_message("❌ Only the gang leader can promote members!", ephemeral=True)
        return

    if target_business_data.get("gang_id") != gang_id:
        await interaction.response.send_message("❌ That user is not in your gang!", ephemeral=True)
        return

    if target_uid == uid:
        await interaction.response.send_message("❌ You can't change your own role!", ephemeral=True)
        return

    old_role = target_business_data.get("gang_role", "member")

    # Update role
    gang_data["members"][target_uid] = role
    target_business_data["gang_role"] = role

    save_business_data(data)

    role_info = GANG_ROLES.get(role, {"name": role})
    old_role_info = GANG_ROLES.get(old_role, {"name": old_role})

    embed = discord.Embed(
        title="⬆️ **Member Promoted** ⬆️",
        description=f"*{user.mention} was promoted from {old_role_info['name']} to {role_info['name']}!*",
        color=0x00FF00
    )

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="war", description="Declare war on another gang")
@app_commands.describe(gang_name="Name of the gang to declare war on")
async def gang_war(interaction: discord.Interaction, gang_name: str):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    # Check permissions
    if user_business_data.get("gang_role") != "leader":
        await interaction.response.send_message("❌ Only the gang leader can declare war!", ephemeral=True)
        return

    # Find target gang
    target_gang_id = None
    target_gang_data = None

    for gid, gdata in gangs_data.items():
        if gdata.get("name", "").lower() == gang_name.lower():
            target_gang_id = gid
            target_gang_data = gdata
            break

    if not target_gang_data:
        await interaction.response.send_message("❌ Gang not found!", ephemeral=True)
        return

    if target_gang_id == gang_id:
        await interaction.response.send_message("❌ You can't declare war on your own gang!", ephemeral=True)
        return

    # Check if already at war
    wars = gang_data.get("wars", {})
    if target_gang_id in wars:
        await interaction.response.send_message("❌ You're already at war with that gang!", ephemeral=True)
        return

    # Create war with enhanced data
    war_id = f"{gang_id}_{target_gang_id}_{int(datetime.now().timestamp())}"

    war_data = {
        "attacker": gang_id,
        "defender": target_gang_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "attacker_members": {},  # {user_id: battles_remaining}
        "defender_members": {},  # {user_id: battles_remaining}
        "battles": {},
        "participants": {},
        "stakes": {"money": 5000000, "territory": True},
        "last_battle": None,
        "max_battles_per_user": 2,  # Each user gets 2 battles max
        "war_type": "elimination"  # War ends when all enemy members eliminated
    }

    # Add war to both gangs
    gang_data.setdefault("wars", {})[target_gang_id] = war_id
    target_gang_data.setdefault("wars", {})[gang_id] = war_id

    # Store war data globally
    data.setdefault("wars", {})[war_id] = war_data

    save_business_data(data)

    # Notify enemy gang leader
    enemy_leader_id = target_gang_data.get("leader")
    if enemy_leader_id:
        try:
            enemy_leader = interaction.client.get_user(int(enemy_leader_id))
            if enemy_leader:
                notify_embed = discord.Embed(
                    title="⚔️ **WAR DECLARED ON YOUR GANG!** ⚔️",
                    description=f"*{gang_data['name']} has declared war on {target_gang_data['name']}!*",
                    color=0xFF0000
                )
                notify_embed.add_field(name="⚔️ **Aggressor**", value=gang_data['name'], inline=True)
                notify_embed.add_field(name="🛡️ **Your Gang**", value=target_gang_data['name'], inline=True)
                notify_embed.add_field(name="💰 **Stakes**", value="$5,000,000 + Territory", inline=True)
                notify_embed.add_field(name="🎯 **Victory**", value="Eliminate all enemy members!", inline=True)
                notify_embed.add_field(name="⚔️ **Action Required**", value="Rally your gang members to fight back!", inline=False)
                notify_embed.set_footer(text="Use /gang battle to participate in the war!")

                await enemy_leader.send(embed=notify_embed)
        except Exception as e:
            print(f"Could not notify enemy gang leader: {e}")

    embed = discord.Embed(
        title="⚔️ **WAR DECLARED!** ⚔️",
        description=f"*{gang_data['name']} has declared war on {target_gang_data['name']}!*",
        color=0xFF0000
    )
    embed.add_field(name="⚔️ **Aggressor**", value=gang_data['name'], inline=True)
    embed.add_field(name="🛡️ **Defender**", value=target_gang_data['name'], inline=True)
    embed.add_field(name="💰 **Stakes**", value="$5,000,000 + Territory", inline=True)
    embed.add_field(name="⚔️ **How to Fight**", value="Use `/gang battle` to participate!", inline=True)
    embed.add_field(name="🎯 **Victory Condition**", value="Eliminate all enemy members!", inline=True)
    embed.add_field(name="⚡ **Battle Limit**", value="2 battles per member", inline=True)
    embed.add_field(name="💀 **Elimination**", value="Lose both battles = eliminated", inline=True)
    embed.add_field(name="📢 **Notification**", value="Enemy gang leader has been notified!", inline=True)
    embed.set_footer(text="Gang war has begun! Fight until one gang is eliminated!")

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="territory", description="View and purchase gang territories")
async def gang_territory(interaction: discord.Interaction):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)
    gang_level = gang_data.get("gang_level", 1)
    is_leader = user_business_data.get("gang_role") == "leader"

    territories = gang_data.get("territories", {})

    class TerritoryView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.button(label="🛒 Purchase Territory", style=discord.ButtonStyle.success)
        async def purchase_territory(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if str(button_interaction.user.id) != uid:
                await button_interaction.response.send_message("❌ This isn't your gang menu!", ephemeral=True)
                return

            if not is_leader:
                await button_interaction.response.send_message("❌ Only the gang leader can purchase territories!", ephemeral=True)
                return

            await show_territory_shop(button_interaction, gang_id, gang_level, data)

        @discord.ui.button(label="💰 Collect Income", style=discord.ButtonStyle.primary)
        async def collect_income(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if str(button_interaction.user.id) != uid:
                await button_interaction.response.send_message("❌ This isn't your gang menu!", ephemeral=True)
                return

            income_per_member = distribute_territory_income(gang_id, data)
            if income_per_member > 0:
                save_business_data(data)
                embed = discord.Embed(
                    title="💰 **Territory Income Distributed!** 💰",
                    description=f"*Each gang member received ${income_per_member:,}!*",
                    color=0x32CD32
                )
                await button_interaction.response.send_message(embed=embed)
            else:
                await button_interaction.response.send_message("❌ No territory income to collect!", ephemeral=True)

    embed = discord.Embed(
        title=f"🗺️ **{gang_data['name']} Territories** 🗺️",
        description="*Your gang's controlled territories*",
        color=0x8B4513
    )

    embed.add_field(name="🏆 **Gang Level**", value=f"`{gang_level}`", inline=True)
    embed.add_field(name="👥 **Members**", value=f"`{len(gang_data.get('members', {}))}`", inline=True)

    if not territories:
        embed.add_field(name="🏜️ **No Territories**", 
                        value="Your gang doesn't control any territories yet.", 
                        inline=False)
        total_income = 0
    else:
        total_income = 0
        territory_list = []
        for territory_id, territory_data in territories.items():
            territory_type = territory_data.get("type", "unknown")
            territory_info = TERRITORY_TYPES.get(territory_type, {})

            income = territory_info.get("income", 0)
            total_income += income

            territory_list.append(f"{territory_info.get('emoji', '🏢')} **{territory_info.get('name', territory_type)}**\n└ ${income:,}/day • {territory_info.get('defense', 0)} defense")

        embed.add_field(
            name="🏢 **Controlled Territories**",
            value="\n\n".join(territory_list),
            inline=False
        )

    embed.add_field(name="💰 **Total Daily Income**", 
                    value=f"`${total_income:,}` (${total_income // len(gang_data.get('members', [uid])):,} per member)", 
                    inline=False)

    if is_leader:
        embed.add_field(name="👑 **Leader Options**", 
                        value="Use the Purchase Territory button to expand your empire!", 
                        inline=False)

    view = TerritoryView() if territories or is_leader else None
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def show_territory_shop(interaction, gang_id, gang_level, data):
    """Show available territories for purchase"""
    gangs_data = data.get("gangs", {})
    gang_data = gangs_data[gang_id]
    owned_territories = gang_data.get("territories", {})
    gambling_data = data.get("gambling", {})
    leader_uid = gang_data["leader"]
    leader_balance = gambling_data.get(leader_uid, {}).get("dollars", 100)


    class TerritorySelect(discord.ui.Select):
        def __init__(self):
            options = []
            requirements = get_territory_unlock_requirements()
            for territory_type, territory_info in TERRITORY_TYPES.items():

                # Check if already owned
                already_owned = any(t.get("type") == territory_type for t in owned_territories.values())

                if already_owned:
                    status = "👑 OWNED"
                elif gang_level >= requirements[territory_type]["gang_level"]:
                    if leader_balance >= requirements[territory_type]["cost"]:
                        status = "✅ Available"
                    else:
                        status = "❌ Can't Afford"
                else:
                    status = f"🔒 Req. Lv.{requirements[territory_type]['gang_level']}"

                options.append(
                    discord.SelectOption(
                        label=f"{territory_info['name']}",
                        description=f"${requirements['cost']:,} - {status} - ${territory_info['income']:,}/day",
                        value=territory_type,
                        emoji=territory_info['emoji']
                    )
                )

            super().__init__(placeholder="Choose territory to purchase...", options=options)

        async def callback(self, callback_interaction: discord.Interaction):
            territory_type = self.values[0]
            await purchase_territory(callback_interaction, gang_id, territory_type, data)

    embed = discord.Embed(
        title="🛒 **Territory Shop** 🛒",
        description="*Expand your gang's influence and income*",
        color=0x32CD32
    )
    embed.add_field(name="🏆 **Gang Level**", value=f"`{gang_level}`", inline=True)
    embed.add_field(name="💰 **Leader Balance**", value=f"`${leader_balance:,}`", inline=True)
    embed.add_field(name="🏢 **Owned Territories**", value=f"`{len(owned_territories)}`", inline=True)

    view = discord.ui.View(timeout=300)
    view.add_item(TerritorySelect())

    await interaction.response.edit_message(embed=embed, view=view)

async def purchase_territory(interaction, gang_id, territory_type, data):
    """Handle territory purchase"""
    gangs_data = data.get("gangs", {})
    gang_data = gangs_data[gang_id]
    gang_level = gang_data.get("gang_level", 1)
    gambling_data = data.get("gambling", {})
    leader_uid = gang_data["leader"]

    territory_info = TERRITORY_TYPES[territory_type]
    requirements = get_territory_unlock_requirements()

    # Check if already owned
    owned_territories = gang_data.get("territories", {})
    already_owned = any(t.get("type") == territory_type for t in owned_territories.values())

    if already_owned:
        await interaction.response.send_message(f"❌ Your gang already owns a {territory_info['name']}!", ephemeral=True)
        return

    # Check gang level requirement
    if gang_level < requirements[territory_type]["gang_level"]:
        await interaction.response.send_message(
            f"❌ Your gang needs to be level {requirements[territory_type]['gang_level']} to purchase {territory_info['name']}! (Currently level {gang_level})", 
            ephemeral=True
        )
        return

    # Check if leader can afford it
    leader_balance = gambling_data.get(leader_uid, {}).get("dollars", 100)
    if leader_balance < requirements[territory_type]["cost"]:
        await interaction.response.send_message(
            f"❌ Gang leader needs ${requirements[territory_type]['cost']:,} but only has ${leader_balance:,}!", 
            ephemeral=True
        )
        return

    # Purchase territory
    gambling_data[leader_uid]["dollars"] -= requirements[territory_type]["cost"]

    territory_id = f"territory_{int(datetime.now().timestamp())}"
    gang_data.setdefault("territories", {})[territory_id] = {
        "type": territory_type,
        "name": territory_info["name"],
        "purchased_at": datetime.now(timezone.utc).isoformat(),
        "purchased_by": leader_uid
    }

    save_business_data(data)

    embed = discord.Embed(
        title="🏢 **Territory Purchased!** 🏢",
        description=f"*Your gang now controls {territory_info['name']}!*",
        color=0x32CD32
    )
    embed.add_field(name=f"{territory_info['emoji']} **Territory**", value=territory_info['name'], inline=True)
    embed.add_field(name="💰 **Cost**", value=f"`${requirements[territory_type]['cost']:,}`", inline=True)
    embed.add_field(name="📈 **Daily Income**", value=f"`${territory_info['income']:,}`", inline=True)
    embed.add_field(name="🛡️ **Defense**", value=f"`{territory_info['defense']}`", inline=True)
    embed.add_field(name="💵 **Leader Balance**", value=f"`${gambling_data[leader_uid]['dollars']:,}`", inline=True)
    embed.set_footer(text="Territory income will be distributed to all gang members!")

    await interaction.response.edit_message(embed=embed, view=None)

@gang_group.command(name="join", description="Request to join a gang")
@app_commands.describe(gang_name="Name of the gang you want to join")
async def gang_join(interaction: discord.Interaction, gang_name: str):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    # Check if user is already in a gang
    if user_business_data.get("gang_id"):
        current_gang_id = user_business_data["gang_id"]
        gangs_data = data.get("gangs", {})
        current_gang = gangs_data.get(current_gang_id, {})
        await interaction.response.send_message(
            f"❌ You're already in **{current_gang.get('name', 'Unknown Gang')}**! Leave first with `/gang leave`.", 
            ephemeral=True)
        return

    # Find the target gang
    gangs_data = data.get("gangs", {})
    target_gang_id = None
    target_gang_data = None

    for gangid, gangdata in gangs_data.items():
        if gangdata.get("name", "").lower() == gang_name.lower():
            target_gang_id = gangid
            target_gang_data = gangdata
            break

    if not target_gang_data:
        # Show available gangs
        available_gangs = [gangdata.get("name", "Unknown") for gangdata in gangs_data.values()]
        if available_gangs:
            gang_list = ", ".join(available_gangs[:5])
            if len(available_gangs) > 5:
                gang_list += f" and {len(available_gangs) - 5} more"
            await interaction.response.send_message(
                f"❌ Gang **{gang_name}** not found!\n\n**Available gangs:** {gang_list}\n\n*Use exact gang name to join.*", 
                ephemeral=True)
        else:
            await interaction.response.send_message("❌ No gangs exist yet! Create one with `/gang create`.", ephemeral=True)
        return

    # Get gang leader for notification
    leader_id = target_gang_data.get("leader")
    if not leader_id:
        await interaction.response.send_message("❌ This gang has no leader!", ephemeral=True)
        return

    # Auto-join the gang (simplified version - you could make this require approval)
    # Add user to gang
    target_gang_data["members"][uid] = "member"
    user_business_data["gang_id"] = target_gang_id
    user_business_data["gang_role"] = "member"

    save_business_data(data)

    # Sync to cross-server network
    try:
        from cross_server_features import sync_gang_cross_server
        server_id = str(interaction.guild.id) if interaction.guild else "0"
        sync_gang_cross_server(str(target_gang_id), target_gang_data, server_id)
    except Exception as e:
        print(f"Cross-server gang sync error: {e}")

    embed = discord.Embed(
        title="✅ **Joined Gang!** ✅",
        description=f"*{interaction.user.mention} successfully joined **{target_gang_data['name']}**!*",
        color=0x00FF00
    )
    embed.add_field(name="👥 **Gang**", value=target_gang_data['name'], inline=True)
    embed.add_field(name="👑 **Leader**", value=f"<@{leader_id}>", inline=True)
    embed.add_field(name="🏷️ **Your Role**", value="Member", inline=True)
    embed.add_field(name="👥 **Total Members**", value=f"`{len(target_gang_data['members'])}`", inline=True)
    embed.add_field(name="📝 **Description**", value=target_gang_data.get('description', 'No description'), inline=False)
    embed.set_footer(text="Welcome to the gang! Use /gang info to see more details.")

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="ganglv", description="[ADMIN ONLY] Set a gang's level on this server")
@app_commands.describe(gang_name="Name of the gang to modify", level="New gang level (1-100)")
async def gang_ganglv(interaction: discord.Interaction, gang_name: str, level: int):
    # Import is_admin from main.py
    from main import is_admin

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("❌ Only admins can modify gang levels.", ephemeral=True)
        return

    if level < 1 or level > 100:
        await interaction.response.send_message("❌ Gang level must be between 1 and 100.", ephemeral=True)
        return

    data = load_business_data()
    gangs_data = data.get("gangs", {})

    # Find gang by name (case insensitive)
    target_gang_id = None
    target_gang_data = None

    for gang_id, gang_data in gangs_data.items():
        if gang_data.get("name", "").lower() == gang_name.lower():
            target_gang_id = gang_id
            target_gang_data = gang_data
            break

    if not target_gang_data:
        await interaction.response.send_message(f"❌ Gang '{gang_name}' not found on this server.", ephemeral=True)
        return

    old_level = target_gang_data.get("gang_level", 1)

    # Calculate XP for the new level
    def calculate_gang_level_xp(level):
        if level <= 1:
            return 0
        return int((level - 1) * 1000 * (1.1 ** (level - 1)))

    new_xp = calculate_gang_level_xp(level)

    # Update gang data
    target_gang_data["gang_level"] = level
    target_gang_data["gang_xp"] = new_xp

    save_business_data(data)

    embed = discord.Embed(
        title="⚡ **Gang Level Modified** ⚡",
        description=f"*Admin {interaction.user.mention} modified gang level*",
        color=0x32CD32
    )
    embed.add_field(name="👥 **Gang**", value=target_gang_data["name"], inline=True)
    embed.add_field(name="📊 **Level Change**", value=f"`{old_level}` → `{level}`", inline=True)
    embed.add_field(name="⭐ **New XP**", value=f"`{new_xp:,}`", inline=True)
    embed.add_field(name="👥 **Members**", value=f"`{len(target_gang_data.get('members', {}))}`", inline=True)
    embed.add_field(name="🔧 **Admin**", value=interaction.user.mention, inline=True)
    embed.set_footer(text="Gang level and XP have been updated!")

    await interaction.response.send_message(embed=embed)

@gang_group.command(name="ganglvr", description="[ADMIN ONLY] Reset ALL gang progress on this server")
async def gang_ganglvr(interaction: discord.Interaction):
    # Import is_admin from main.py
    from main import is_admin

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("❌ Only admins can reset gang progress.", ephemeral=True)
        return

    data = load_business_data()
    gangs_data = data.get("gangs", {})

    if not gangs_data:
        await interaction.response.send_message("❌ No gangs exist to reset.", ephemeral=True)
        return

    class ConfirmResetView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="🗑️ CONFIRM RESET", style=discord.ButtonStyle.danger)
        async def confirm_reset(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message("❌ Only the admin who initiated this can confirm!", ephemeral=True)
                return

            # Count what we're resetting
            gang_count = len(gangs_data)
            total_territories = sum(len(gang.get("territories", {})) for gang in gangs_data.values())

            # Reset all gang data
            data["gangs"] = {}

            # Remove gang memberships from all users
            business_data = data.get("business", {})
            users_reset = 0
            for uid, user_data in business_data.items():
                if user_data.get("gang_id"):
                    user_data["gang_id"] = None
                    user_data["gang_role"] = None
                    users_reset += 1

            save_business_data(data)

            embed = discord.Embed(
                title="🗑️ **ALL GANG PROGRESS RESET** 🗑️",
                description="*Complete gang system reset performed by admin*",
                color=0xFF0000
            )
            embed.add_field(name="👥 **Gangs Deleted**", value=f"`{gang_count}`", inline=True)
            embed.add_field(name="🏠 **Territories Lost**", value=f"`{total_territories}`", inline=True)
            embed.add_field(name="👤 **Members Reset**", value=f"`{users_reset}`", inline=True)
            embed.add_field(name="💰 **Treasury Lost**", value="All gang funds", inline=True)
            embed.add_field(name="⚔️ **Wars Ended**", value="All active wars", inline=True)
            embed.add_field(name="🎯 **Equipment Reset**", value="All gang weapons/armor", inline=True)
            embed.add_field(name="🔧 **Reset By**", value=interaction.user.mention, inline=True)
            embed.add_field(name="📅 **Reset Date**", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", inline=True)
            embed.add_field(
                name="📋 **What Was Reset**",
                value="• All gang levels and XP\n• All gang memberships\n• All territories and income\n• All gang wars and battles\n• All gang equipment and weapons\n• All gang achievements and research\n• All gang treasury funds",
                inline=False
            )
            embed.set_footer(text="🌍 Fresh start for all gangs! Players can now create new gangs.")

            await button_interaction.response.edit_message(embed=embed, view=None)

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_reset(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message("❌ Only the admin who initiated this can cancel!", ephemeral=True)
                return

            await button_interaction.response.edit_message(content="❌ Gang reset cancelled.", embed=None, view=None)

    # Show confirmation dialog
    gang_count = len(gangs_data)
    total_territories = sum(len(gang.get("territories", {})) for gang in gangs_data.values())

    embed = discord.Embed(
        title="⚠️ **CONFIRM GANG RESET** ⚠️",
        description="*This will permanently delete ALL gang progress on this server!*",
        color=0xFF6B6B
    )
    embed.add_field(name="⚠️ **WARNING**", value="**THIS ACTION CANNOT BE UNDONE!**\nAll gang progress will be permanently lost.", inline=False)
    embed.add_field(name="🛡️ **Server Protection**", value="This only affects gangs on this server.\nCross-server data is protected.", inline=False)
    embed.set_footer(text="⚠️ Think carefully before confirming this action!")

    await interaction.response.send_message(embed=embed, view=ConfirmResetView())

@gang_group.command(name="register", description="Register your gang in the global cross-server network")
async def gang_register(interaction: discord.Interaction):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    if not gang_data:
        await interaction.response.send_message("❌ Gang data not found!", ephemeral=True)
        return

    # Check if user is the gang leader
    if user_business_data.get("gang_role") != "leader":
        await interaction.response.send_message("❌ Only gang leaders can register the gang in the global network!", ephemeral=True)
        return

    try:
        from cross_server_features import sync_gang_cross_server, load_cross_server_data
        server_id = str(interaction.guild.id) if interaction.guild else "0"

        # Sync the gang to cross-server network
        sync_gang_cross_server(gang_id, gang_data, server_id)

        # Verify registration was successful
        cross_server_data = load_cross_server_data()
        global_gangs = cross_server_data.get("global_gangs", {})

        if gang_id in global_gangs:
            global_gang = global_gangs[gang_id]

            embed = discord.Embed(
                title="🌍 **Gang Registered!** 🌍",
                description=f"*{gang_data['name']} has been successfully registered in the global cross-server network!*",
                color=0x32CD32
            )
            embed.add_field(name="👥 **Gang Name**", value=gang_data['name'], inline=True)
            embed.add_field(name="🏠 **Home Server**", value=interaction.guild.name if interaction.guild else "Unknown", inline=True)
            embed.add_field(name="🌟 **Global Level**", value=f"`{global_gang['global_level']}`", inline=True)
            embed.add_field(name="🏆 **Reputation**", value=f"`{global_gang['reputation']}`", inline=True)
            embed.add_field(name="🌐 **Network Status**", value="✅ **Registered**", inline=True)
            embed.add_field(name="💡 **Benefits**", 
                          value="• Cross-server gang wars\n• Global gang leaderboard\n• Multi-server expansion", 
                          inline=False)
            embed.set_footer(text="🌍 Your gang is now part of the global network!")

            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Registration failed! Please try again.", ephemeral=True)

    except ImportError:
        await interaction.response.send_message("❌ Cross-server features are not available!", ephemeral=True)
    except Exception as e:
        print(f"Gang registration error: {e}")
        await interaction.response.send_message("❌ An error occurred during registration. Please try again.", ephemeral=True)

@gang_group.command(name="list", description="View all gangs on the server")
async def gang_list(interaction: discord.Interaction):
    data = load_business_data()
    gangs_data = data.get("gangs", {})

    if not gangs_data:
        await interaction.response.send_message("❌ No gangs exist yet! Create one with `/gang create`.", ephemeral=True)
        return

    embed = discord.Embed(
        title="👥 **All Gangs** 👥",
        description="*List of all gangs on this server*",
        color=0xFF0000
    )

    for gang_id, gang_data in gangs_data.items():
        member_count = len(gang_data.get("members", {}))
        leader_id = gang_data.get("leader")

        embed.add_field(
            name=f"👑 **{gang_data['name']}**",
            value=f"Leader: <@{leader_id}>\nMembers: {member_count}\nLevel: {gang_data.get('base_level', 1)}",
            inline=True
        )

    embed.add_field(
        name="💡 **How to Join**",
        value="Use `/gang join <gang_name>` to join a gang!",
        inline=False
    )

    embed.add_field(
        name="🌍 **Global Network**",
        value="Use `/crossserver gangs` to see gangs across all servers!",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

# Battle system with different styles and level effects
BATTLE_STYLES = {
    "aggressive": {
        "name": "Aggressive Attack",
        "emoji": "⚔️",
        "description": "High risk, high reward battle style",
        "damage_multiplier": 1.5,
        "accuracy": 0.7,
        "level_importance": 0.3
    },
    "defensive": {
        "name": "Defensive Strategy",
        "emoji": "🛡️", 
        "description": "Consistent damage with high accuracy",
        "damage_multiplier": 1.0,
        "accuracy": 0.9,
        "level_importance": 0.4
    },
    "tactical": {
        "name": "Tactical Approach",
        "emoji": "🎯",
        "description": "Balanced strategy relying on skill",
        "damage_multiplier": 1.2,
        "accuracy": 0.8,
        "level_importance": 0.5
    },
    "overwhelming": {
        "name": "Overwhelming Force",
        "emoji": "💥",
        "description": "Pure power, level-dependent",
        "damage_multiplier": 1.3,
        "accuracy": 0.6,
        "level_importance": 0.7
    }
}

def calculate_battle_outcome(attacker_level, defender_level, attacker_style, defender_style):
    """Calculate battle outcome based on levels and battle styles"""

    attacker_info = BATTLE_STYLES[attacker_style]
    defender_info = BATTLE_STYLES[defender_style]

    # Base damage calculation
    attacker_damage = 10 * attacker_info["damage_multiplier"]
    defender_damage = 10 * defender_info["damage_multiplier"]

    # Level effect calculation
    level_diff = attacker_level - defender_level
    attacker_level_bonus = level_diff * attacker_info["level_importance"] * 2
    defender_level_bonus = -level_diff * defender_info["level_importance"] * 2

    # Apply level bonuses
    attacker_damage += attacker_level_bonus
    defender_damage += defender_level_bonus

    # Accuracy check
    attacker_hits = random.random() < attacker_info["accuracy"]
    defender_hits = random.random() < defender_info["accuracy"]

    # Calculate final damage
    final_attacker_damage = attacker_damage if attacker_hits else 0


@gang_group.command(name="battle", description="Fight in an active gang war or challenge another gang member")
@app_commands.describe(target_user="Optional: Challenge a specific user to a friendly battle")
async def gang_battle(interaction: discord.Interaction, target_user: Optional[discord.Member] = None):
    data = load_business_data()
    uid = str(interaction.user.id)
    user_business_data = get_user_business_data(uid, data)

    gang_id = user_business_data.get("gang_id")
    if not gang_id:
        await interaction.response.send_message("❌ You're not in a gang!", ephemeral=True)
        return

    # Get user level from gambling data
    gambling_data = data.get("gambling", {})
    user_gambling = gambling_data.get(uid, {"xp": 0})

    from smoke_features import calculate_level
    user_level = calculate_level(user_gambling.get("xp", 0))

    gangs_data = data.get("gangs", {})
    gang_data = gangs_data.get(gang_id)

    # Check if this is a friendly battle challenge
    if target_user:
        target_uid = str(target_user.id)
        target_business_data = get_user_business_data(target_uid, data)
        target_gang_id = target_business_data.get("gang_id")

        if not target_gang_id:
            await interaction.response.send_message("❌ Target user is not in a gang!", ephemeral=True)
            return

        # Allow friendly battles between gang members for training
        is_gang_training = (target_gang_id == gang_id)

        # Get target user level
        target_gambling = gambling_data.get(target_uid, {"xp": 0})
        target_level = calculate_level(target_gambling.get("xp", 0))

        # Send battle invitation to target user
        await send_battle_invitation(interaction, uid, target_uid, user_level, target_level, data, is_gang_training, target_user)
        return

    # Continue with war battle logic
    wars_data = data.get("wars", {})

    # Find active war
    active_war = None
    enemy_gang_id = None

    for enemy_id, war_id_ref in gang_data.get("wars", {}).items():
        if war_id_ref in wars_data and wars_data[war_id_ref]["status"] == "active":
            active_war = wars_data[war_id_ref]
            enemy_gang_id = enemy_id
            break

    if not active_war:
        await interaction.response.send_message("❌ Your gang is not in an active war! Use `/gang battle @user` for friendly battles.", ephemeral=True)
        return

    # Start war battle - simplified implementation with notification
    await start_war_battle_with_notification(interaction, uid, user_level, active_war, enemy_gang_id, data)

async def send_battle_invitation(interaction, uid, target_uid, user_level, target_level, data, is_gang_training, target_user):
    """Send battle invitation to target user"""

    class BattleInviteView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="⚔️ Accept Battle", style=discord.ButtonStyle.success)
        async def accept_battle(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != target_user.id:
                await button_interaction.response.send_message("❌ This invitation isn't for you!", ephemeral=True)
                return

            # Start the battle
            await start_friendly_battle_simple(button_interaction, uid, target_uid, user_level, target_level, data, is_gang_training)

        @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
        async def decline_battle(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            if button_interaction.user.id != target_user.id:
                await button_interaction.response.send_message("❌ This invitation isn't for you!", ephemeral=True)
                return

            embed = discord.Embed(
                title="❌ **Battle Declined** ❌",
                description=f"*{target_user.mention} declined the battle invitation*",
                color=0xFF0000
            )
            await button_interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="⚔️ **Battle Invitation** ⚔️",
        description=f"*{interaction.user.mention} challenges {target_user.mention} to combat!*",
        color=0xFFFF00
    )
    embed.add_field(name="🥊 **Challenger**", value=f"{interaction.user.mention}\nLevel {user_level}", inline=True)
    embed.add_field(name="🛡️ **Challenged**", value=f"{target_user.mention}\nLevel {target_level}", inline=True)
    embed.add_field(name="⚖️ **Battle Type**", value="Gang Training" if is_gang_training else "Inter-Gang Battle", inline=True)
    embed.add_field(name="💡 **Balanced Combat**", value="Damage, defense, and accuracy have been balanced for fair fights between all levels!", inline=False)
    embed.set_footer(text="⏰ Invitation expires in 60 seconds")

    await interaction.response.send_message(embed=embed, view=BattleInviteView())

async def start_friendly_battle_simple(interaction, uid, target_uid, user_level, target_level, data, is_gang_training=False):
    """Interactive friendly battle implementation"""
    from battle_system import BattlePlayer, StreetBattle, create_battle_embed, active_battles

    # Get user equipment using local functions
    equipment_data = load_equipment_data()
    user_equipment = get_user_equipment(uid, equipment_data)
    target_equipment = get_user_equipment(target_uid, equipment_data)

    # Get target user and ensure proper username handling
    target_user = interaction.client.get_user(int(target_uid))
    if target_user:
        target_username = target_user.display_name
    else:
        # Try to get username from gambling data
        gambling_data = data.get("gambling", {})
        target_gambling = gambling_data.get(target_uid, {})
        target_username = target_gambling.get("username", f"Player {target_uid[:8]}")

    # Create battle players with proper names
    player1 = BattlePlayer(
        uid, 
        interaction.user.display_name, 
        user_level,
        user_equipment.get("current_weapon", "fists"),
        user_equipment.get("current_clothing", "street_clothes")
    )

    player2 = BattlePlayer(
        target_uid,
        target_username,
        target_level,
        target_equipment.get("current_weapon", "fists"),
        target_equipment.get("current_clothing", "street_clothes")
    )

    # Create battle
    battle = StreetBattle(player1, player2, "friendly")

    # Store battle with both possible keys for proper lookup
    battle_key = f"{uid}_{target_uid}"
    reverse_key = f"{target_uid}_{uid}"
    active_battles[battle_key] = battle
    active_battles[reverse_key] = battle

    # Create battle embed and view
    embed = create_battle_embed(battle)
    if is_gang_training:
        embed.title = "🥊 **Gang Training Battle** 🥊"
        embed.description = "*Friendly training between gang members!*"
    else:
        embed.title = "⚔️ **Inter-Gang Battle** ⚔️"
        embed.description = "*Turn-based combat between rival gangs!*"

    # Create custom battle view that handles both players properly
    view = FriendlyBattleActionView(battle, uid, target_uid, data)

    await interaction.response.send_message(embed=embed, view=view)

class FriendlyBattleActionView(discord.ui.View):
    def __init__(self, battle, player1_id: str, player2_id: str, data: dict):
        super().__init__(timeout=300)
        self.battle = battle
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.data = data

    @discord.ui.button(label="⚔️ Attack", style=discord.ButtonStyle.danger)
    async def attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_battle_action(interaction, "attack")

    @discord.ui.button(label="💥 Heavy Attack", style=discord.ButtonStyle.danger)
    async def heavy_attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_battle_action(interaction, "heavy_attack")

    @discord.ui.button(label="⚡ Quick Attack", style=discord.ButtonStyle.primary)
    async def quick_attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_battle_action(interaction, "quick_attack")

    @discord.ui.button(label="🛡️ Defend", style=discord.ButtonStyle.secondary)  
    async def defend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_battle_action(interaction, "defend")

    @discord.ui.button(label="😤 Intimidate", style=discord.ButtonStyle.secondary)
    async def intimidate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_battle_action(interaction, "intimidate")

    @discord.ui.button(label="✨ Special", style=discord.ButtonStyle.success)
    async def special_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_battle_action(interaction, "special")

    async def handle_battle_action(self, interaction: discord.Interaction, action: str):
        user_id = str(interaction.user.id)

        # Check if it's the current player's turn
        current_player_id = self.battle.player1.user_id if self.battle.current_turn == 1 else self.battle.player2.user_id
        
        if user_id != current_player_id:
            # Get current player name for better error message
            try:
                current_user = interaction.client.get_user(int(current_player_id))
                current_name = current_user.display_name if current_user else f"Player {current_player_id[:8]}"
            except:
                current_name = f"Player {current_player_id[:8]}"
            
            await interaction.response.send_message(f"❌ It's not your turn! Current turn: {current_name}", ephemeral=True)
            return

        # Execute the action
        result = self.battle.execute_action(action)

        if result.get("battle_end"):
            # Battle is over
            await self.award_friendly_battle_rewards(interaction, result)

            # Remove from active battles
            from battle_system import active_battles
            battle_key = f"{self.battle.player1.user_id}_{self.battle.player2.user_id}"
            reverse_key = f"{self.battle.player2.user_id}_{self.battle.player1.user_id}"
            if battle_key in active_battles:
                del active_battles[battle_key]
            if reverse_key in active_battles:
                del active_battles[reverse_key]

            # Show final result
            if result["winner"] == "Draw":
                embed = discord.Embed(
                    title="🤝 **Battle Draw!** 🤝",
                    description=result["message"],
                    color=0xFFFF00
                )
            else:
                embed = discord.Embed(
                    title=f"🏆 **{result['winner']} Wins!** 🏆",
                    description=result["message"],
                    color=0x00FF00
                )

            await interaction.response.edit_message(embed=embed, view=None)
        else:
            # Show action result temporarily, then update to battle view
            action_embed = discord.Embed(
                title="⚔️ **Battle Action** ⚔️",
                description=result["message"],
                color=0xFF6B6B if not result.get("hit", True) else 0x00FF00
            )

            # First, show the action result
            await interaction.response.edit_message(embed=action_embed, view=None)

            # Wait a moment, then show the updated battle state
            import asyncio
            await asyncio.sleep(2)

            # Continue battle
            from battle_system import create_battle_embed
            battle_embed = create_battle_embed(self.battle)
            battle_embed.title = "⚔️ **Friendly Battle** ⚔️"

            new_view = FriendlyBattleActionView(self.battle, self.player1_id, self.player2_id, self.data)
            await interaction.edit_original_response(embed=battle_embed, view=new_view)

    async def award_friendly_battle_rewards(self, interaction: discord.Interaction, result: dict):
        """Award XP and money for friendly battles"""
        gambling_data = self.data.get("gambling", {})

        # Award rewards to both players
        for player in [self.battle.player1, self.battle.player2]:
            uid = player.user_id
            if uid not in gambling_data:
                gambling_data[uid] = {"dollars": 100, "xp": 0}

            # Award rewards based on outcome
            if result["winner"] == player.username:
                # Winner rewards
                xp_gain = 100 + (player.level * 10)
                money_gain = 50000 + (player.level * 5000)
                gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + xp_gain
                gambling_data[uid]["dollars"] = gambling_data[uid].get("dollars", 100) + money_gain
            elif result["winner"] != "Draw":
                # Loser consolation
                xp_gain = 50 + (player.level * 5)
                gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + xp_gain
            else:
                # Draw rewards
                xp_gain = 75 + (player.level * 7)
                money_gain = 25000 + (player.level * 2500)
                gambling_data[uid]["xp"] = gambling_data[uid].get("xp", 0) + xp_gain
                gambling_data[uid]["dollars"] = gambling_data[uid].get("dollars", 100) + money_gain

        save_business_data(self.data)

# Add equipment shop and loadout commands
equipment_group = app_commands.Group(name="equipment", description="Buy weapons, armor and gear")

@equipment_group.command(name="shop", description="Browse and purchase weapons and armor")
async def equipment_shop(interaction: discord.Interaction):
    data = load_business_data()
    equipment_data = load_equipment_data()
    uid = str(interaction.user.id)

    # Get user balance and level
    gambling_data = data.get("gambling", {})
    user_gambling = gambling_data.get(uid, {"dollars": 100})
    current_balance = user_gambling.get("dollars", 100)

    from smoke_features import calculate_level
    user_level = calculate_level(user_gambling.get("xp", 0))

    user_equipment = get_user_equipment(uid, equipment_data)

    class ShopCategorySelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label="🔫 Weapons", value="weapons", emoji="🔫"),
                discord.SelectOption(label="🧥 Clothing/Armor", value="clothing", emoji="🧥")
            ]
            super().__init__(placeholder="Choose equipment category...", options=options)

        async def callback(self, interaction: discord.Interaction):
            category = self.values[0]
            if category == "weapons":
                await show_weapon_shop(interaction, current_balance, user_equipment)
            else:
                await show_clothing_shop(interaction, current_balance, user_equipment)

    embed = discord.Embed(
        title="🛒 **Equipment Shop** 🛒",
        description="*Upgrade your street fighting gear*",
        color=0x32CD32
    )
    embed.add_field(name="💰 **Your Balance**", value=f"`${current_balance:,}`", inline=True)
    embed.add_field(name="🏆 **Your Level**", value=f"`{user_level}`", inline=True)
    embed.add_field(name="🔫 **Current Weapon**", value=user_equipment["current_weapon"].replace("_", " ").title(), inline=True)
    embed.add_field(name="🧥 **Current Clothing**", value=user_equipment["current_clothing"].replace("_", " ").title(), inline=True)

    view = discord.ui.View(timeout=300)
    view.add_item(ShopCategorySelect())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def show_weapon_shop(interaction, current_balance, user_equipment):
    from battle_system import STREET_WEAPONS

    # Get user level
    data = load_business_data()
    uid = str(interaction.user.id)
    gambling_data = data.get("gambling", {})
    user_gambling = gambling_data.get(uid, {"xp": 0})

    from smoke_features import calculate_level
    user_level = calculate_level(user_gambling.get("xp", 0))

    class WeaponSelect(discord.ui.Select):
        def __init__(self):
            options = []
            owned_weapons = user_equipment.get("weapons", ["fists"])

            for weapon_id, weapon_info in STREET_WEAPONS.items():
                cost = weapon_info["cost"]
                level_req = weapon_info.get("level_req", 1)

                if weapon_id in owned_weapons:
                    status = "👑 OWNED"
                elif user_level < level_req:
                    status = f"🔒 Lv.{level_req}"
                elif cost <= current_balance:
                    status = "✅"
                elif cost == 0:
                    status = "🆓"
                else:
                    status = "❌"

                options.append(
                    discord.SelectOption(
                        label=weapon_info["name"],
                        description=f"${cost:,} {status} - DMG: {weapon_info['damage']} ACC: {weapon_info['accuracy']}%",
                        value=weapon_id,
                        emoji=weapon_info["emoji"]
                    )
                )

            super().__init__(placeholder="Choose a weapon to purchase...", options=options[:25])

        async def callback(self, interaction: discord.Interaction):
            weapon_id = self.values[0]
            weapon_info = STREET_WEAPONS[weapon_id]
            cost = weapon_info["cost"]
            level_req = weapon_info.get("level_req", 1)

            # Reload user equipment data in callback
            equipment_data = load_equipment_data()
            uid = str(interaction.user.id)
            user_equipment = get_user_equipment(uid, equipment_data)
            owned_weapons = user_equipment.get("weapons", ["fists"])

            if weapon_id in owned_weapons:
                await interaction.response.send_message(f"❌ You already own {weapon_info['name']}!", ephemeral=True)
                return

            if user_level < level_req:
                await interaction.response.send_message(f"❌ You need level {level_req} to purchase {weapon_info['name']}! (Currently level {user_level})", ephemeral=True)
                return

            if current_balance < cost:
                await interaction.response.send_message(f"❌ You need ${cost:,} but only have ${current_balance:,}!", ephemeral=True)
                return

            # Purchase weapon
            data = load_business_data()
            gambling_data = data.get("gambling", {})
            uid = str(interaction.user.id)
            gambling_data[uid]["dollars"] -= cost

            equipment_data = load_equipment_data()
            user_equipment = get_user_equipment(uid, equipment_data)
            user_equipment["weapons"].append(weapon_id)

            save_business_data(data)
            save_equipment_data(equipment_data)

            embed = discord.Embed(
                title="🔫 **Weapon Purchased!** 🔫",
                description=f"*You bought {weapon_info['name']}!*",
                color=0x00FF00
            )
            embed.add_field(name="🔫 **Weapon**", value=weapon_info["name"], inline=True)
            embed.add_field(name="💰 **Cost**", value=f"`${cost:,}`", inline=True)
            embed.add_field(name="💵 **Remaining**", value=f"`${gambling_data[uid]['dollars']:,}`", inline=True)
            embed.add_field(name="💥 **Damage**", value=f"`{weapon_info['damage']}`", inline=True)
            embed.add_field(name="🎯 **Accuracy**", value=f"`{weapon_info['accuracy']}%`", inline=True)
            embed.add_field(name="💨 **Speed**", value=f"`{weapon_info['speed']}`", inline=True)
            embed.set_footer(text="Use /equipment loadout to equip your new weapon!")

            await interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="🔫 **Weapon Shop** 🔫",
        description="*Choose your firepower*",
        color=0xFF0000
    )

    view = discord.ui.View(timeout=300)
    view.add_item(WeaponSelect())
    await interaction.response.edit_message(embed=embed, view=view)

async def show_clothing_shop(interaction, current_balance, user_equipment):
    from battle_system import STREET_CLOTHING

    # Get user level
    data = load_business_data()
    uid = str(interaction.user.id)
    gambling_data = data.get("gambling", {})
    user_gambling = gambling_data.get(uid, {"xp": 0})

    from smoke_features import calculate_level
    user_level = calculate_level(user_gambling.get("xp", 0))

    class ClothingSelect(discord.ui.Select):
        def __init__(self):
            options = []
            owned_clothing = user_equipment.get("clothing", ["street_clothes"])

            for clothing_id, clothing_info in STREET_CLOTHING.items():
                cost = clothing_info["cost"]
                level_req = clothing_info.get("level_req", 1)

                if clothing_id in owned_clothing:
                    status = "👑 OWNED"
                elif user_level < level_req:
                    status = f"🔒 Lv.{level_req}"
                elif cost <= current_balance:
                    status = "✅"
                elif cost == 0:
                    status = "🆓"
                else:
                    status = "❌"

                options.append(
                    discord.SelectOption(
                        label=clothing_info["name"],
                        description=f"${cost:,} {status} - DEF: {clothing_info['defense']} HP: +{clothing_info['health']}",
                        value=clothing_id,
                        emoji=clothing_info["emoji"]
                    )
                )

            super().__init__(placeholder="Choose clothing/armor to purchase...", options=options[:25])

        async def callback(self, interaction: discord.Interaction):
            clothing_id = self.values[0]
            clothing_info = STREET_CLOTHING[clothing_id]
            cost = clothing_info["cost"]
            level_req = clothing_info.get("level_req", 1)

            # Reload user equipment data in callback
            equipment_data = load_equipment_data()
            uid = str(interaction.user.id)
            user_equipment = get_user_equipment(uid, equipment_data)
            owned_clothing = user_equipment.get("clothing", ["street_clothes"])

            if clothing_id in owned_clothing:
                await interaction.response.send_message(f"❌ You already own {clothing_info['name']}!", ephemeral=True)
                return

            if user_level < level_req:
                await interaction.response.send_message(f"❌ You need level {level_req} to purchase {clothing_info['name']}! (Currently level {user_level})", ephemeral=True)
                return

            if current_balance < cost:
                await interaction.response.send_message(f"❌ You need ${cost:,} but only have ${current_balance:,}!", ephemeral=True)
                return

            # Purchase clothing
            data = load_business_data()
            gambling_data = data.get("gambling", {})
            uid = str(interaction.user.id)
            gambling_data[uid]["dollars"] -= cost

            equipment_data = load_equipment_data()
            user_equipment = get_user_equipment(uid, equipment_data)
            user_equipment["clothing"].append(clothing_id)

            save_business_data(data)
            save_equipment_data(equipment_data)

            embed = discord.Embed(
                title="🧥 **Clothing Purchased!** 🧥",
                description=f"*You bought {clothing_info['name']}!*",
                color=0x00FF00
            )
            embed.add_field(name="🧥 **Clothing**", value=clothing_info["name"], inline=True)
            embed.add_field(name="💰 **Cost**", value=f"`${cost:,}`", inline=True)
            embed.add_field(name="💵 **Remaining**", value=f"`${gambling_data[uid]['dollars']:,}`", inline=True)
            embed.add_field(name="🛡️ **Defense**", value=f"`{clothing_info['defense']}`", inline=True)
            embed.add_field(name="❤️ **Health Bonus**", value=f"`+{clothing_info['health']}`", inline=True)
            embed.add_field(name="💨 **Speed**", value=f"`{clothing_info['speed']}`", inline=True)
            embed.set_footer(text="Use /equipment loadout to equip your new clothing!")

            await interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="🧥 **Clothing & Armor Shop** 🧥",
        description="*Protect yourself in style*",
        color=0x0000FF
    )

    view = discord.ui.View(timeout=300)
    view.add_item(ClothingSelect())
    await interaction.response.edit_message(embed=embed, view=view)

@equipment_group.command(name="loadout", description="View and change your equipment loadout")
async def equipment_loadout(interaction: discord.Interaction):
    from battle_system import STREET_WEAPONS, STREET_CLOTHING

    equipment_data = load_equipment_data()
    uid = str(interaction.user.id)
    user_equipment = get_user_equipment(uid, equipment_data)

    class LoadoutView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.button(label="🔫 Change Weapon", style=discord.ButtonStyle.primary)
        async def change_weapon(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            await show_weapon_selector(button_interaction, user_equipment)

        @discord.ui.button(label="🧥 Change Clothing", style=discord.ButtonStyle.secondary)
        async def change_clothing(self, button_interaction: discord.Interaction, button: discord.ui.Button):
            await show_clothing_selector(button_interaction, user_equipment)

    # Current loadout
    current_weapon = STREET_WEAPONS[user_equipment["current_weapon"]]
    current_clothing = STREET_CLOTHING[user_equipment["current_clothing"]]

    embed = discord.Embed(
        title="⚔️ **Your Combat Loadout** ⚔️",
        description="*Your current battle equipment*",
        color=0x800080
    )

    embed.add_field(
        name=f"{current_weapon['emoji']} **Current Weapon**",
        value=f"**{current_weapon['name']}**\nDamage: {current_weapon['damage']}\nAccuracy: {current_weapon['accuracy']}%\nSpeed: {current_weapon['speed']}",
        inline=True
    )

    embed.add_field(
        name=f"{current_clothing['emoji']} **Current Clothing**",
        value=f"**{current_clothing['name']}**\nDefense: {current_clothing['defense']}\nHealth: +{current_clothing['health']}\nSpeed: {current_clothing['speed']}",
        inline=True
    )

    # Owned equipment count
    embed.add_field(
        name="📦 **Inventory**",
        value=f"Weapons: {len(user_equipment['weapons'])}\nClothing: {len(user_equipment['clothing'])}",
        inline=True
    )

    view = LoadoutView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def show_weapon_selector(interaction, user_equipment):
    from battle_system import STREET_WEAPONS

    class WeaponLoadoutSelect(discord.ui.Select):
        def __init__(self):
            options = []
            owned_weapons = user_equipment.get("weapons", ["fists"])
            current_weapon = user_equipment.get("current_weapon", "fists")

            for weapon_id in owned_weapons:
                weapon_info = STREET_WEAPONS[weapon_id]
                status = "🟢 EQUIPPED" if weapon_id == current_weapon else ""

                options.append(
                    discord.SelectOption(
                        label=weapon_info["name"],
                        description=f"{status} - DMG: {weapon_info['damage']} ACC: {weapon_info['accuracy']}%",
                        value=weapon_id,
                        emoji=weapon_info["emoji"]
                    )
                )

            super().__init__(placeholder="Choose weapon to equip...", options=options)

        async def callback(self, interaction: discord.Interaction):
            weapon_id = self.values[0]
            weapon_info = STREET_WEAPONS[weapon_id]

            # Update equipment
            equipment_data = load_equipment_data()
            uid = str(interaction.user.id)
            user_equipment = get_user_equipment(uid, equipment_data)
            user_equipment["current_weapon"] = weapon_id
            save_equipment_data(equipment_data)

            embed = discord.Embed(
                title="🔫 **Weapon Equipped!** 🔫",
                description=f"*You equipped {weapon_info['name']}!*",
                color=0x00FF00
            )
            embed.add_field(name="🔫 **Weapon**", value=weapon_info["name"], inline=True)
            embed.add_field(name="💥 **Damage**", value=f"`{weapon_info['damage']}`", inline=True)
            embed.add_field(name="🎯 **Accuracy**", value=f"`{weapon_info['accuracy']}%`", inline=True)

            await interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="🔫 **Select Weapon** 🔫",
        description="*Choose from your owned weapons*",
        color=0xFF0000
    )

    view = discord.ui.View(timeout=300)
    view.add_item(WeaponLoadoutSelect())
    await interaction.response.edit_message(embed=embed, view=view)

async def show_clothing_selector(interaction, user_equipment):
    from battle_system import STREET_CLOTHING

    class ClothingLoadoutSelect(discord.ui.Select):
        def __init__(self):
            options = []
            owned_clothing = user_equipment.get("clothing", ["street_clothes"])
            current_clothing = user_equipment.get("current_clothing", "street_clothes")

            for clothing_id in owned_clothing:
                clothing_info = STREET_CLOTHING[clothing_id]
                status = "🟢 EQUIPPED" if clothing_id == current_clothing else ""

                options.append(
                    discord.SelectOption(
                        label=clothing_info["name"],
                        description=f"{status} - DEF: {clothing_info['defense']} HP: +{clothing_info['health']}",
                        value=clothing_id,
                        emoji=clothing_info["emoji"]
                    )
                )

            super().__init__(placeholder="Choose clothing to equip...", options=options)

        async def callback(self, interaction: discord.Interaction):
            clothing_id = self.values[0]
            clothing_info = STREET_CLOTHING[clothing_id]

            # Update equipment
            equipment_data = load_equipment_data()
            uid = str(interaction.user.id)
            user_equipment = get_user_equipment(uid, equipment_data)
            user_equipment["current_clothing"] = clothing_id
            save_equipment_data(equipment_data)

            embed = discord.Embed(
                title="🧥 **Clothing Equipped!** 🧥",
                description=f"*You equipped {clothing_info['name']}!*",
                color=0x00FF00
            )
            embed.add_field(name="🧥 **Clothing**", value=clothing_info["name"], inline=True)
            embed.add_field(name="🛡️ **Defense**", value=f"`{clothing_info['defense']}`", inline=True)
            embed.add_field(name="❤️ **Health Bonus**", value=f"`+{clothing_info['health']}`", inline=True)

            await interaction.response.edit_message(embed=embed, view=None)

    embed = discord.Embed(
        title="🧥 **Select Clothing** 🧥",
        description="*Choose from your owned clothing*",
        color=0x0000FF
    )

    view = discord.ui.View(timeout=300)
    view.add_item(ClothingLoadoutSelect())
    await interaction.response.edit_message(embed=embed, view=view)





@equipment_group.command(name="arsenal", description="View your complete equipment collection")
async def equipment_arsenal(interaction: discord.Interaction):
    from battle_system import STREET_WEAPONS, STREET_CLOTHING

    equipment_data = load_equipment_data()
    uid = str(interaction.user.id)
    user_equipment = get_user_equipment(uid, equipment_data)

    embed = discord.Embed(
        title="🔫 **Your Arsenal** 🔫",
        description="*Your complete equipment collection*",
        color=0x800080
    )

    # Weapons
    owned_weapons = user_equipment.get("weapons", ["fists"])
    current_weapon = user_equipment.get("current_weapon", "fists")

    weapon_list = []
    for weapon_id in owned_weapons:
        weapon_info = STREET_WEAPONS[weapon_id]
        status = "🟢" if weapon_id == current_weapon else "⚪"
        weapon_list.append(f"{status} {weapon_info['emoji']} **{weapon_info['name']}**")

    embed.add_field(
        name="🔫 **Weapons**",
        value="\n".join(weapon_list) if weapon_list else "None",
        inline=True
    )

    # Clothing
    owned_clothing = user_equipment.get("clothing", ["street_clothes"])
    current_clothing = user_equipment.get("current_clothing", "street_clothes")

    clothing_list = []
    for clothing_id in owned_clothing:
        clothing_info = STREET_CLOTHING[clothing_id]
        status = "🟢" if clothing_id == current_clothing else "⚪"
        clothing_list.append(f"{status} {clothing_info['emoji']} **{clothing_info['name']}**")

    embed.add_field(
        name="🧥 **Clothing/Armor**",
        value="\n".join(clothing_list) if clothing_list else "None",
        inline=True
    )

    embed.set_footer(text="🟢 = Equipped | Use /equipment shop to buy more gear!")
    await interaction.response.send_message(embed=embed, ephemeral=True)