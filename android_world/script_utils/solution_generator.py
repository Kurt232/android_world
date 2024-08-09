import ast
import json
import os

from android_world.env import interface
from android_world.agents import agent_utils
from android_world.script_utils import tools
from android_world.script_utils.api_doc import ApiDoc

class SolutionGenerator:

  def __init__(self, env: interface.AsyncEnv, app_name: str, doc: ApiDoc):
    self.env = env
    self.app_name = app_name
    self.doc = doc
    
  def make_prompt(self, ele_data, task, app_name):
    # all elements
    all_elements_desc = ''
    for element in ele_data['elements']:
      all_elements_desc += f"\n\nelement: {element['api_name']} \n\tDescription: {element['description']} \n\tType: {element['element_type']}"
      if 'effect' in element.keys():
        all_elements_desc += f"\n\tEffect: {element['effect']}"
    
    # current screen elements
    current_screen_elements = ''
    
    state = self.env.get_state()
    element_tree = agent_utils.forest_to_element_tree(state.forest)
    current_screen_name = self.doc.get_screen_name_by_skeleton(element_tree.skeleton)
    if not current_screen_name:
      current_screen_name = self.doc.main_screen
    
    # valid_elements
    valid_element_list = self.doc.get_valid_element_list(current_screen_name, element_tree.str)
    
    for ele in valid_element_list:
      current_screen_elements += f"\n\nelement: {ele.api_name} \n\tDescription: {ele.description} \n\tType: {ele.element_type}"
      if ele.effect:
        current_screen_elements += f"\n\tEffect: {ele.effect}"

    return f'''Imagine that you are a robot operating a smartphone to use the {app_name} app. Like how humans operate the smartphone, you can tap, long tap, input text, scroll, and get attributes of the UI elements in the {app_name} app. However, unlike humans, you cannot see the screen or interact with the physical buttons on the smartphone. Therefore, you need to write scripts to manipulate the UI elements (buttons, text fields, scrollers, element_lists, etc) in the app. 

Here is an example script to complete the task:

```python
# task: Open a note or create a note titled 'note_test' if there is none.
notes = $open_note_title_list

for i in range(len(notes)):
  note = notes[i]
  title = note.get_text($note_title)
  if title == 'note_test':
    note.tap(title)
    return

back()
tap($create_note)
set_text($add_note_title, 'note_test')
tap($text_note_type)
tap($add_note_ok)
```

Above is an example. 
**Your ultimate task is: {task}**

In the script, except for the common python control flow (for, if-else, function def/calls, etc.), you can use the following APIs:
- tap(<element_selector>) -> None: tap on the element. Almost all elements can be taped. If an element's attribute checked=false or selected=false, tapping it can make it checked or selected, vice versa.
- long_tap(<element_selector>) -> None: long tap the element. 
- set_text(<element_selector>, <text>) -> None: set the text of the element to <text>. Only editable text fields can be set text.
- scroll(<element_selector>, <direction>) -> bool: scroll the UI element in the specified direction, and direction is a str from "up", 'down", "left", "right". e.g. scroll($scroll_settings_page, "down")
- get_text(<element_selector>) -> str: return the text of the element as a string.
- get_attributes(<element_selector>) -> dict[str, str]: return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
- back(): close the current window


The <element_selector> primitive is used to select an element, possible ways of selection include:
- $<element id>, eg. $settings_button
- <element_list>[<idx>]: the idx-th in the element list. eg. $my_items[1]

The <element_list> primitive is used to select a list of elements, possible ways of selection include:
- <element_selector>: the items in the list element identified by <element_selector>. eg. $my_items
- <element_list>.match(<text or attribute dict>): the elements in the element list that match the given text or attribute dict. eg. $my_items.match("key words") or $my_items.match({{"selected": true}})
You can use len(<element_list>) to get the total number of items in an element list.

Each <element_selector> can refer to a single element or an element contained multiple elements, especially in the case of complex items within an <element_list>. The following APIs are supported to be invoked as member functions to limit their effect domain: `tap`, `long_tap`, `set_text`, `scroll`, `get_text`, `get_attributes`, and `back`. Note that these APIs still need to satisfy the required arguments. If the APIs are invoked as member functions, they will only affect the element selected by the <element_selector>, while the APIs invoked as global functions will affect all elements in the phone screen. For example, `$note_list[1].tap($note_title)` will tap the title of the second note in the note list, whereas `tap($note_title)` will always tap the first note title in the note list.

You can start with the elements in current screen:
{current_screen_elements}

You can use the following important UI elements:
{all_elements_desc}


Your answer should follow this JSON format:

{{
    "plan": "<a high level plan to complete the task>",
    "elements": "<analyze the elements that could be used to complete the task>", 
    "script": "<the python script to complete the task>"
}}

**Note that you should only output the JSON content.**'''

  def get_solution(self, app_name,
                   prompt_answer_path,
                   task: str,
                   ele_data_path: str,
                   model_name='gpt-4o'):
    # formatted_apis = self.format_all_apis(enable_dependency)
    ele_data = tools.load_json_file(ele_data_path)
    prompt = self.make_prompt(
        task=task, app_name=app_name, ele_data=ele_data)
    answer = tools.query_gpt(prompt=prompt, model=model_name)
    tools.dump_json_file(prompt_answer_path, {
        'prompt': prompt,
        'answer': answer
    })
    answer = tools.convert_gpt_answer_to_json(
        answer, model_name=model_name, default_value={
            'Plan': '',
            'Script': ''
        })
    if 'Script' in answer.keys():
      return answer['Script']
    else:
      return answer['script']
