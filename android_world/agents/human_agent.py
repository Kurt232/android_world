# Copyright 2024 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Agent for human playing."""

import datetime
import sys

from android_world.agents import base_agent
from android_world.agents import human_agent_utils
from android_world.env import interface
from android_world.env import json_action


class HumanAgent(base_agent.EnvironmentInteractingAgent):
  """Human agent; wait for user to indicate they are done."""

  def __init__(self,
               env: interface.AsyncEnv,
               save_path: str,
               name: str = 'HumanAgent'):

    super().__init__(env, name)
    self.save_path = save_path

  def step(self, goal: str) -> base_agent.AgentInteractionResult:
    del goal
    action_list = [
        "wait", "click", "long_press", "scroll", "input_text", "navigate_home",
        "navigate_back", "open_app", "answer", "keyboard_enter", "status"
    ]

    print('\033[0;32m', '-' * 40, 'Actions', '-' * 40, '\033[0m')
    print('\n'.join(
        [f'{index}: {action}' for index, action in enumerate(action_list)]))
    response = input('Please input the action id (or q to quit):')
    if response == 'q':
      sys.exit()
    try:
      response = int(response)
    except:
      print('\033[1;31m' + 'Invalid id. converting to wait action.' + '\033[0m')
      response = 0

    action_wait = {'action_type': 'wait'}

    action_type = action_list[response]
    print(f'Action: {action_type}')
    action_details = {'action_type': action_type}

    state = self.get_post_transition_state()
    element_tree = human_agent_utils.forest_to_element_tree(state.forest)

    if action_type == "status":
      goal_status = ['complete', 'infeassible']
      status_id = input(f'Please input the status id in {goal_status}.')
      try:
        status = goal_status[int(status_id)]
        action_details['goal_status'] = status
      except:
        print('\033[1;31m' + 'Invalid id. converting to wait action.' +
              '\033[0m')
        action_details = action_wait
    elif action_type == "answer":
      action_details['text'] = input('Please input the text:')
    elif action_type in ["click", "long_press", "input_text", "scroll"]:
      print('\033[0;32m', '-' * 40, 'State', '-' * 40, '\033[0m')
      print(element_tree.get_str(is_color=True))
      ele_id = input('Please input the element id:')
      try:
        ele_id = int(ele_id)
        ele = element_tree.ele_map[ele_id]
        x, y = ele.ele.bbox_pixels.center
        x, y = int(x), int(y)
        action_details['x'] = x
        action_details['y'] = y
        if action_type == "input_text":
          action_details['text'] = input('Please input the text:')
        elif action_type == "scroll":
          action_details['bbox_pixels'] = ele.ele.bbox_pixels
          direction_list = ['up', 'down', 'left', 'right']
          direction = input(
              f'Please input the direction id in {direction_list}:')
          try:
            direction = direction_list[int(direction)]
            action_details['direction'] = direction
          except:
            print('\033[1;31m' + 'Invalid id. converting to wait action.' +
                  '\033[0m')
            action_details = action_wait
      except:
        print('\033[1;31m' + 'Invalid id. converting to wait action.' +
              '\033[0m')
        action_details = action_wait
    elif action_type == "open_app":
      app_name = input(
          'Please input the app name\n(nothing will happen if the app is not installed):\n'
      )
      action_details['app_name'] = app_name

    self.env.execute_action(json_action.JSONAction(**action_details))

    result = {}
    result['elements'] = state.ui_elements

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_T%H%M%S')

    human_agent_utils.save_to_yaml(self.save_path, element_tree.str, timestamp,
                                   action_type, action_details,
                                   action_details.get('text', None),
                                   self.env.device_screen_size[0],
                                   self.env.device_screen_size[1])

    human_agent_utils.save_screenshot(self.save_path, timestamp,
                                      state.pixels.copy())

    return base_agent.AgentInteractionResult(False, result)

  def get_post_transition_state(self) -> interface.State:
    return self.env.get_state()
