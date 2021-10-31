import collections
import math, sys
from os import urandom
from lux.game import Game
from lux.game_map import Cell, RESOURCE_TYPES
from lux.constants import Constants
from lux.game_constants import GAME_CONSTANTS
from lux import annotate
import numpy as np
from collections import deque
import random

#Next need to improve the AI in general (when to build cities, where to build cities, when to build new tiles, etc.)
#Problems putting cities next to each other
#incentivize putting cities in a specific direction towards more resources? Maybe list of possible cities and check each one?
#Probably need to improve movement but holy fuck was that tedious this time so I don't really want to do it again
#It seems to expand to quickly early game but not quickly enough late game
    #change vars for check_new_city based on turn number to encourage more cities late game?
#could also find distances to resources other than wood and if it is worth the turns to get there, could be better to mine them instead
#really I just need to be able to code without being a fucking idiot (not possible)


logfile = "agent2.log"

open(logfile,"w")

DIRECTIONS = Constants.DIRECTIONS
game_state = None
build_location = None

unit_to_city_dict = {} #maps each worker to a city tile
unit_to_resource_dict = {} #maps each woker to a resource
worker_positions = {} #contains the current position for every worker
IMMEDIATE_moves = {} #contains moves that are of high prio i.e. Building city
IMMEDIATE_moves_dict = {} #contains list of moves to allow avoiding of cities

statsfile = "agent2.txt"

def get_resource_tiles(game_state, width, height): #gets all of the resource tiles in the game
    resource_tiles: list[Cell] = []
    for y in range(height):
        for x in range(width):
            cell = game_state.map.get_cell(x, y)
            if cell.has_resource():
                resource_tiles.append(cell)
    return resource_tiles


def get_close_resource(unit, resource_tiles, player): #finds the closest resource
    closest_dist = math.inf
    closest_resource_tile = None
    for resource_tile in resource_tiles:
        if resource_tile.resource.type == Constants.RESOURCE_TYPES.COAL and not player.researched_coal(): continue
        if resource_tile.resource.type == Constants.RESOURCE_TYPES.URANIUM and not player.researched_uranium(): continue
        if resource_tile in unit_to_resource_dict.values(): continue    

        dist = resource_tile.pos.distance_to(unit.pos)
        if dist < closest_dist:
            closest_dist = dist
            closest_resource_tile = resource_tile
    return closest_resource_tile


def get_close_city(player, unit): #finds the closest city
    closest_dist = math.inf
    closest_city_tile = None
    for k, city in player.cities.items():
        for city_tile in city.citytiles:
            dist = city_tile.pos.distance_to(unit.pos)
            if dist < closest_dist:
                closest_dist = dist
                closest_city_tile = city_tile
    return closest_city_tile


def find_empty_tile_near(near_what, game_state, observation): #finds an empty tile near another tile, mostly used for building cities
    build_location = None
    count = 1

    while(build_location == None):
        with open(logfile,"a") as f:
            f.write(f"{observation['step']}: Trying to find tile with count = {count}\n")
        dirs = [(count,0), (0,count), (-1*count,0), (0,-1*count), (count,-1*count), (-1*count,count), (-1*count,-1*count), (count,count)]
        for d in dirs:
                if near_what.pos.x+d[0] >= game_state.map.width or near_what.pos.y+d[1] >= game_state.map.height:
                        continue
                possible_empty_tile = game_state.map.get_cell(near_what.pos.x+d[0], near_what.pos.y+d[1])
                if possible_empty_tile.resource == None and possible_empty_tile.road == 0 and possible_empty_tile.citytile == None:
                    build_location = possible_empty_tile
                    with open(logfile,"a") as f:
                        f.write(f"{observation['step']}: Found build location:{build_location.pos}\n")
                    return build_location

        count += 1
    with open(logfile,"a") as f:
        f.write(f"{observation['step']}: Something went VERY FUCKING WRONG\n")
    return None

def check_minable(player, resource_tile): #checks if a resource is minable based on research points
    if resource_tile.resource.type == Constants.RESOURCE_TYPES.COAL and not player.researched_coal():
        return False
    if resource_tile.resource.type == Constants.RESOURCE_TYPES.URANIUM and not player.researched_uranium():
        return False
    return True

def find_groups_of_resources(player, game_state, resource_tiles, unit): #searches the map for the closest group of resources to expand city to
    dirs = [(1,0), (0,1), (-1,0), (0,-1)]
    resource_tiles_scoped = resource_tiles.copy()
    while len(resource_tiles_scoped) > 0:
        resource = get_close_resource(unit, resource_tiles_scoped, player)
        resource_tiles_scoped.remove(resource)
        resource_count = 0
        if not check_minable(player, resource):
            resource_loop = False
        else:
            resource_loop = True
        while(resource_loop and resource_count < 4):
            for d in dirs:
                if resource.pos.x+d[0] >= game_state.map.width or resource.pos.y+d[1] >= game_state.map.height:
                    continue
                possible_resource = game_state.map.get_cell(resource.pos.x+d[0], resource.pos.y+d[1])
                if possible_resource.has_resource():
                    resource_loop = True
                    resource_count += 1
                else:
                    resource_loop = False
        if resource_count >= 4:
            return resource

def check_new_city(cities, observation, game_state, player): #checks to see if making a new city is a good choice
    dirs = [(1,0), (0,1), (-1,0), (0,-1)]
    if (observation['step'] % 40) > 25:
        with open(logfile,"a") as f:
            f.write(f"{observation['step']}: Too close to night to build new city\n")
        return False
    adj_resources_to_city = 0
    city_tiles = []
    for city in cities:
        for city_tile in city.citytiles:
            city_tiles.append(city_tile)
            for d in dirs:
                if city_tile.pos.x+d[0] >= game_state.map.width or city_tile.pos.y+d[1] >= game_state.map.width:
                    continue
                check_tile = game_state.map.get_cell(city_tile.pos.x+d[0], city_tile.pos.y+d[1])
                if check_tile.has_resource():
                    if check_minable(player, check_tile):
                        adj_resources_to_city += 1
    if(len(cities) == 1):
        if len(city_tiles) < 3:
            return False
    with open(logfile,"a") as f:
        f.write(f"{observation['step']}: adj_resources_to_city: {adj_resources_to_city}\n")
    if adj_resources_to_city <= 2:
        return True
    return False

def check_collision(next_pos_tuple, city_tiles, avoid_cities, observation): #checks to see if collision will occur for a given movement
    global worker_positions

    city_tiles_tuple = []
    for c in city_tiles:
        city_tiles_tuple.append((c.pos.x, c.pos.y))
    if avoid_cities and next_pos_tuple in city_tiles_tuple:
        with open(logfile,"a") as f:
            f.write(f"{observation['step']}: Collision issues: avoid cities\n")
        return 2
    if next_pos_tuple in city_tiles_tuple:
        return 0
    if next_pos_tuple in worker_positions.values():
        with open(logfile,"a") as f:
            f.write(f"{observation['step']}: Collision issues: worker collision\n")
        return 1
    return 0

def new_move(unit, move_to_cell, observation, city_tiles, avoid_cities): #move function that takes into account more variables
    global game_state
    global worker_positions

    next_pos = unit.pos.translate(unit.pos.direction_to(move_to_cell.pos),1)
    next_pos_tuple = (next_pos.x, next_pos.y)
    if unit.id in worker_positions:
        del worker_positions[unit.id]
    collision_value = check_collision(next_pos_tuple, city_tiles, avoid_cities, observation)   
    if collision_value == 2:
        return None
    if collision_value:
        rand_dir = random.choice(["n","s","e","w"])
        next_pos = unit.pos.translate(rand_dir,1)
        next_pos_tuple = (next_pos.x, next_pos.y)
        worker_positions[unit.id] = next_pos_tuple
        return rand_dir
    return_action = unit.pos.direction_to(move_to_cell.pos)
    worker_positions[unit.id]=next_pos_tuple
    return return_action

def action_from_IMM(unit, observation, city_tiles): #moves and creates city for IMMEDIATE actions (like building a city)
    global IMMEDIATE_moves
    move_to_cell = IMMEDIATE_moves[unit.id]
    curr_pos = unit.pos
    move_list_temp = []
    if unit.id in IMMEDIATE_moves_dict:
        move = IMMEDIATE_moves_dict[unit.id].pop(~0)
        with open(logfile,"a") as f:
            f.write(f"{observation['step']}: popped = {move}\n")
        if len(IMMEDIATE_moves_dict[unit.id]) == 0:
            del IMMEDIATE_moves_dict[unit.id]
        return move
    IMMEDIATE_moves_dict[unit.id] = []
    return_val = new_move(unit, move_to_cell, observation, city_tiles, 1)
    if return_val == None:
        direction = unit.pos.direction_to(move_to_cell.pos)
        if direction == 'n':
            with open(logfile,"a") as f:
                f.write(f"{observation['step']}: here\n")
            IMMEDIATE_moves_dict[unit.id].append('n')
            curr_pos = curr_pos.translate('n',1)
            IMMEDIATE_moves_dict[unit.id].append('w')
            curr_pos = curr_pos.translate('w',1)
        elif direction == 'e':
            with open(logfile,"a") as f:
                f.write(f"{observation['step']}: here2\n")
            IMMEDIATE_moves_dict[unit.id].append('e')
            curr_pos = curr_pos.translate('e',1)
            IMMEDIATE_moves_dict[unit.id].append('s')
            curr_pos = curr_pos.translate('s',1)
        elif direction == 's':
            with open(logfile,"a") as f:
                f.write(f"{observation['step']}: here3\n")
            IMMEDIATE_moves_dict[unit.id].append('s')
            curr_pos = curr_pos.translate('s',1)
            IMMEDIATE_moves_dict[unit.id].append('w')
            curr_pos = curr_pos.translate('w',1)
        elif direction == 'w':
            with open(logfile,"a") as f:
                f.write(f"{observation['step']}: here3\n")
            IMMEDIATE_moves_dict[unit.id].append('w')
            curr_pos = curr_pos.translate('w',1)
            IMMEDIATE_moves_dict[unit.id].append('n')
            curr_pos = curr_pos.translate('n',1)
    else:
        IMMEDIATE_moves_dict[unit.id].append(return_val)
        curr_pos = curr_pos.translate(return_val,1)
    with open(logfile,"a") as f:
        f.write(f"{observation['step']}: Curr_pos: {curr_pos}, move_to_cell: {move_to_cell.pos}\n")

    IMMEDIATE_moves_dict[unit.id].append('c')


    


def agent(observation, configuration):
    global game_state
    global build_location
    global unit_to_city_dict
    global unit_to_resource_dict
    global worker_positions
    global IMMEDIATE_moves

    ### Do not edit ###
    if observation["step"] == 0:
        game_state = Game()
        game_state._initialize(observation["updates"])
        game_state._update(observation["updates"][2:])
        game_state.id = observation.player
    else:
        game_state._update(observation["updates"])
    
    actions = []

    ### AI Code goes down here! ### 
    player = game_state.players[observation.player]
    opponent = game_state.players[(observation.player + 1) % 2]
    width, height = game_state.map.width, game_state.map.height
    resource_tiles = get_resource_tiles(game_state, width, height)
    workers = [u for u in player.units if u.is_worker()]

    for w in workers:

        if w.id in worker_positions:
            worker_positions[w.id] = (w.pos.x, w.pos.y)
        else:
            worker_positions[w.id] = (w.pos.x, w.pos.y)

        if w.id not in unit_to_city_dict:
            with open(logfile, "a") as f:
                f.write(f"{observation['step']} Found worker unaccounted for {w.id}\n")
            city_assignment = get_close_city(player, w)
            unit_to_city_dict[w.id] = city_assignment

    with open(logfile, "a") as f:
        f.write(f"{observation['step']} Worker Positions {worker_positions}\n")


    for w in workers:
        if w.id not in unit_to_resource_dict:
            with open(logfile, "a") as f:
                f.write(f"{observation['step']} Found worker w/o resource {w.id}\n")

            resource_assignment = get_close_resource(w, resource_tiles, player)
            unit_to_resource_dict[w.id] = resource_assignment



    cities = player.cities.values()
    city_tiles = []

    for city in cities:
        for c_tile in city.citytiles:
            city_tiles.append(c_tile)


    build_city = False

    if len(city_tiles):
        if len(workers) / len(city_tiles) >= 0.75:
            build_city = True
    else:
        build_city = True

    # we iterate over all our units and do something with them
    already_building_city = False
    for unit in player.units:
        if unit.is_worker() and unit.can_act():
            with open(logfile, "a") as f:
                f.write(f"{observation['step']} IMMEDIATE_moves: {IMMEDIATE_moves}\n")
            if unit.id in IMMEDIATE_moves:
                move_direction = action_from_IMM(unit, observation, city_tiles)
                if move_direction == DIRECTIONS.CENTER:
                    with open(logfile, "a") as f:
                        f.write(f"{observation['step']} Building City\n")
                    actions.append(unit.build_city())
                    del IMMEDIATE_moves[unit.id]
                    build_location = None
                else:
                    actions.append(unit.move(move_direction))
                continue
            try:

                if unit.get_cargo_space_left() > 0:
                    intended_resource = unit_to_resource_dict[unit.id]
                    cell = game_state.map.get_cell(intended_resource.pos.x, intended_resource.pos.y)

                    if cell.has_resource():
                        actions.append(unit.move(new_move(unit, intended_resource, observation, city_tiles, False)))

                    else:
                        intended_resource = get_close_resource(unit, resource_tiles, player)
                        unit_to_resource_dict[unit.id] = intended_resource
                        actions.append(unit.move(new_move(unit, intended_resource, observation, city_tiles, False)))

                else:
                    enough_mats = (unit.cargo.wood + (unit.cargo.coal * 10) + (unit.cargo.uranium * 40)) >= 100
                    with open(logfile, "a") as f:
                        f.write(f"{observation['step']} Enough_mats: {enough_mats}\n")
                    if build_city and not already_building_city and enough_mats:
                        already_building_city = True
                        associated_city_id = unit_to_city_dict[unit.id].cityid
                        unit_city = [c for c in cities if c.cityid == associated_city_id][0]
                        unit_city_fuel = unit_city.fuel
                        unit_city_size = len(unit_city.citytiles)
                        if(unit_city_size < 3):
                            enough_fuel = (unit_city_fuel/unit_city_size) > 250
                        else:
                            enough_fuel = (unit_city_fuel/unit_city_size) > 300
                        
                        enough_fuel_new_city = (unit_city_fuel/unit_city_size) > 350

                        with open(logfile, "a") as f:
                            f.write(f"{observation['step']} Build city stuff: {associated_city_id}, fuel {unit_city_fuel}, size {unit_city_size}, enough fuel {enough_fuel}\n")


                        if enough_fuel:
                            with open(logfile, "a") as f:
                                f.write(f"{observation['step']} We want to build a city tile!\n")
                            if build_location is None:
                                if check_new_city(cities, observation, game_state, player) or enough_fuel_new_city:
                                    with open(logfile, "a") as f:
                                        f.write(f"{observation['step']} Create a new city!\n")
                                    resource_group = find_groups_of_resources(player, game_state, resource_tiles, unit)
                                    build_location = find_empty_tile_near(resource_group, game_state, observation)
                                else:
                                    empty_near = get_close_city(player, unit)
                                    build_location = find_empty_tile_near(empty_near, game_state, observation)
                                IMMEDIATE_moves[unit.id] = build_location

                            if unit.pos == build_location.pos:
                                action = unit.build_city()
                                actions.append(action)

                                build_city = False
                                build_location = None
                                with open(logfile, "a") as f:
                                    f.write(f"{observation['step']} Built the city!\n")
                                continue   

                            else:
                                with open(logfile, "a") as f:
                                    f.write(f"{observation['step']}: Navigating to where we wish to build!\n")
                                actions.append(unit.move(new_move(unit, build_location, observation, city_tiles, True)))


                                continue

                        elif len(player.cities) > 0:
                            if unit.id in unit_to_city_dict and unit_to_city_dict[unit.id] in city_tiles:
                                actions.append(unit.move(new_move(unit, unit_to_city_dict, observation, city_tiles, False)))

                            else:
                                unit_to_city_dict[unit.id] = get_close_city(player,unit)
                                actions.append(unit.move(new_move(unit, unit_to_city_dict[unit.id], observation, city_tiles, False)))

                    # if unit is a worker and there is no cargo space left, and we have cities, lets return to them
                    elif len(player.cities) > 0:
                        if unit.id in unit_to_city_dict and unit_to_city_dict[unit.id] in city_tiles:
                            actions.append(unit.move(new_move(unit, unit_to_city_dict[unit.id], observation, city_tiles, False)))

                        else:
                            unit_to_city_dict[unit.id] = get_close_city(player,unit)
                            actions.append(unit.move(new_move(unit, unit_to_city_dict[unit.id], observation, city_tiles, False)))

            except Exception as e:
                with open(logfile, "a") as f:
                    f.write(f"{observation['step']}: Unit error {str(e)} \n")



    can_create = len(city_tiles) - len(workers)

    if len(city_tiles) > 0:
        for city_tile in city_tiles:
            if city_tile.can_act():
                if can_create > 0:
                    actions.append(city_tile.build_worker())
                    can_create -= 1
                    with open(logfile, "a") as f:
                        f.write(f"{observation['step']}: Created a worker \n")
                else:
                    actions.append(city_tile.research())
                    with open(logfile, "a") as f:
                        f.write(f"{observation['step']}: Doing research! \n")


    if observation["step"] == 359:
        with open(statsfile,"a") as f:
            f.write(f"{len(city_tiles)}\n")
    
    return actions