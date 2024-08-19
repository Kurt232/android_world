'''
move this file to ./ and run
'''
import os
import json
from typing import Any

from android_world.agents import code_agent
from android_world.env import env_launcher
from android_world import suite_utils
from android_world.agents import code_agent
from android_world.env import env_launcher
from android_world import episode_runner

from android_world.task_evals.single.recipe import RecipeDeleteDuplicateRecipes, RecipeAddMultipleRecipes
from android_world.task_evals.utils.sqlite_schema_utils import Recipe

def _find_adb_directory() -> str:
  """Returns the directory where adb is located."""
  potential_paths = [
      os.path.expanduser('~/Library/Android/sdk/platform-tools/adb'),
      os.path.expanduser('~/Android/Sdk/platform-tools/adb'),
  ]
  for path in potential_paths:
    if os.path.isfile(path):
      return path
  raise EnvironmentError(
      'adb not found in the common Android SDK paths. Please install Android'
      " SDK and ensure adb is in one of the expected directories. If it's"
      ' already installed, point to the installed location.'
  )  

def test_correct_code(path: int, is_fixed: bool = True):
  '''
  RecipeDeleteDuplicateRecipes
  no-fixed acc: 5/5
  fixed    acc: 10/10
  '''
  task_obj = RecipeDeleteDuplicateRecipes
  code = """\
# task: Delete all but one of any recipes in the Broccoli app that are exact duplicates, ensuring at least one instance of each unique recipe remains
done = False
while not done:
  current_recipes = $main_screen__recipe_card_list
  seen_recipes = set()
  current_done = True
  for i in range(len(current_recipes)):
    recipe = current_recipes[i]
    title = recipe.get_text($main_screen__recipe_card_title)
    description = recipe.get_text($main_screen__recipe_card_description)
    if (title, description) in seen_recipes:
      tap(recipe.match(title))
      tap($recipe_details_screen__more_options_button)
      tap($recipe_details_more_options_popup__delete_button)
      tap($delete_confirmation_dialog__delete_button)
      current_done = False
      break
      # slide effect, delete one element will change the layout
    else:
      seen_recipes.add((title, description))

  if current_done:
    is_to_bottom = scroll($main_screen__recipe_card_list, "down")
    if is_to_bottom:
      done = True
"""

  env = env_launcher.load_and_setup_env(
    console_port=5554,
    emulator_setup=False,
    adb_path=_find_adb_directory(),
  )
  env_launcher.verify_api_level(env)

  save_dir = path
  if os.path.exists(save_dir):
    import shutil
    shutil.rmtree(save_dir)
  os.makedirs(save_dir)

  if is_fixed:
    params = {'row_objects': [Recipe(title='Chicken Alfredo Pasta', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='45 mins', source='', ingredients='adjustable', directions='Cook fettuccine pasta, toss with Alfredo sauce and grilled chicken strips. Serve with a sprinkle of Parmesan cheese. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chicken Alfredo Pasta', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='45 mins', source='', ingredients='adjustable', directions='Cook fettuccine pasta, toss with Alfredo sauce and grilled chicken strips. Serve with a sprinkle of Parmesan cheese. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1)], 'noise_row_objects': [Recipe(title='Chicken Caesar Salad Wrap', description='A delicious and healthy choice for any time of the day.', servings='1 serving', preparationTime='1 hrs', source='', ingredients='to your liking', directions='Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Butternut Squash Soup', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='1 serving', preparationTime='45 mins', source='', ingredients='see directions', directions='Sauté onions and garlic, add cubed butternut squash and broth. Puree until smooth and season with nutmeg, salt, and pepper. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Caprese Salad Skewers', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='3 hrs', source='', ingredients='as per recipe', directions='Thread cherry tomatoes, basil leaves, and mozzarella balls onto skewers. Drizzle with balsamic glaze. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Beef Stir Fry', description='A quick and easy meal, perfect for busy weekdays.', servings='8 servings', preparationTime='20 mins', source='', ingredients='optional ingredients', directions='Stir-fry beef slices with broccoli, bell peppers, and onions in soy sauce and garlic. Serve over rice or noodles. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chickpea Vegetable Soup', description='A delicious and healthy choice for any time of the day.', servings='2 servings', preparationTime='30 mins', source='', ingredients='as desired', directions='Sauté onions, carrots, and celery, add broth, canned tomatoes, and chickpeas. Simmer with spinach and seasonings. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1)], 'seed': 30}
  else:
    params = task_obj.generate_random_params()
    params['seed'] = 30
  task = task_obj(params)
  
  open('tmp/code.txt', 'w').write(code)
  open('tmp/app_name.txt', 'w').write('broccoli')
  
  agent = code_agent.CodeAgent(env, save_dir, [task.name])
  agent.FREEZED_CODE = True
  agent.MAX_RETRY_TIMES = 1 # only execute once for code script
  
  def run_episode(task):
    return episode_runner.run_episode(
      goal=task.goal,
      agent=agent,
      max_n_steps=int(10 * task.complexity),
      start_on_home_screen=True,
      termination_fn=None
    )
  
  result = suite_utils._run_task(
    task,
    run_episode,
    env,
    False
  )
  print(f'{result["is_successful"]=}')
  
  open(f'{save_dir}/task_info.txt', 'w').write(str(task.__dict__))
  open(f'{save_dir}/result.txt', 'w').write(f'is_successful={result["is_successful"]}\n{is_fixed=}\n' + str(result))
  
  env.close()
  return result["is_successful"]

def test_correct_code1(path: str):
  '''
  RecipeAddMultipleRecipes
  '''
  task_obj = RecipeAddMultipleRecipes
  code = """\
def add_recipe(title, description, servings, preparation_time, ingredients, directions):
  tap($main_screen__new_recipe_button)
  set_text($new_recipe_screen__title_input, title)
  set_text($new_recipe_screen__description_input, description)
  set_text($new_recipe_screen__servings_input, servings)
  set_text($new_recipe_screen__preparation_time_input, preparation_time)
  set_text($new_recipe_screen__ingredients_input, ingredients)
  scroll($new_recipe_screen__scroll_down, 'down')
  set_text($new_recipe_screen__directions_input, directions)
  tap($new_recipe_screen__save_button)
  back()

recipes = [
    {
      'title': 'Chicken Caesar Salad Wrap',
      'description': 'A quick and easy meal, perfect for busy weekdays.',
      'servings': '8 servings',
      'preparationTime': '20 mins',
      'ingredients': 'subject to change',
      'directions': 'Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Garnish with fresh herbs for a more vibrant taste.'
    },
    {
      'title': 'Quinoa Salad with Vegetables',
      'description': 'A delicious and healthy choice for any time of the day.',
      'servings': '1 serving',
      'preparationTime': '1 hrs',
      'ingredients': 'flexible ingredients',
      'directions': 'Mix cooked quinoa with diced vegetables, feta cheese, and a lemon olive oil dressing. Feel free to substitute with ingredients you have on hand.'
    },
    {
      'title': 'Beef Stir Fry',
      'description': 'A quick and easy meal, perfect for busy weekdays.',
      'servings': '2 servings',
      'preparationTime': '30 mins',
      'ingredients': 'various amounts',
      'directions': 'Stir-fry beef slices with broccoli, bell peppers, and onions in soy sauce and garlic. Serve over rice or noodles. Feel free to substitute with ingredients you have on hand.'
    }
]

for recipe in recipes:
  add_recipe(recipe['title'], recipe['description'], recipe['servings'], recipe['preparationTime'], recipe['ingredients'], recipe['directions'])
"""

  env = env_launcher.load_and_setup_env(
    console_port=5554,
    emulator_setup=False,
    adb_path=_find_adb_directory(),
  )
  env_launcher.verify_api_level(env)
  
  save_dir = path
  if os.path.exists(save_dir):
    import shutil
    shutil.rmtree(save_dir)
  os.makedirs(save_dir)
  

  params = {'row_objects': [Recipe(title='Chicken Caesar Salad Wrap', description='A quick and easy meal, perfect for busy weekdays.', servings='8 servings', preparationTime='20 mins', source='', ingredients='subject to change', directions='Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Quinoa Salad with Vegetables', description='A delicious and healthy choice for any time of the day.', servings='1 serving', preparationTime='1 hrs', source='', ingredients='flexible ingredients', directions='Mix cooked quinoa with diced vegetables, feta cheese, and a lemon olive oil dressing. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Beef Stir Fry', description='A quick and easy meal, perfect for busy weekdays.', servings='2 servings', preparationTime='30 mins', source='', ingredients='various amounts', directions='Stir-fry beef slices with broccoli, bell peppers, and onions in soy sauce and garlic. Serve over rice or noodles. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1)], 'noise_row_objects': [Recipe(title='Greek Salad Pita Pockets', description='A delicious and healthy choice for any time of the day.', servings='6 servings', preparationTime='20 mins', source='', ingredients='adjustable', directions='Fill pita pockets with lettuce, cucumber, tomato, feta, olives, and Greek dressing. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Raspberry Almond Smoothie', description='A quick and easy meal, perfect for busy weekdays.', servings='8 servings', preparationTime='10 mins', source='', ingredients='see directions', directions='Blend together raspberries, almond milk, banana, and a scoop of almond butter until smooth. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Baked Cod with Lemon and Dill', description='A delicious and healthy choice for any time of the day.', servings='1 serving', preparationTime='20 mins', source='', ingredients='to preference', directions='Place cod fillets in a baking dish, season with lemon juice, dill, salt, and pepper. Bake until fish flakes easily. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chickpea Vegetable Soup', description='A quick and easy meal, perfect for busy weekdays.', servings='6 servings', preparationTime='45 mins', source='', ingredients='n/a', directions='Sauté onions, carrots, and celery, add broth, canned tomatoes, and chickpeas. Simmer with spinach and seasonings. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Sweet Potato and Black Bean Tacos', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='6 servings', preparationTime='20 mins', source='', ingredients='to your liking', directions='Roast sweet potato cubes, mix with black beans, and use as filling for tacos. Top with avocado and cilantro lime sauce. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Avocado Toast with Egg', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='8 servings', preparationTime='1 hrs', source='', ingredients='various amounts', directions='Toast bread, top with mashed avocado, a fried egg, salt, pepper, and chili flakes. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Raspberry Almond Smoothie', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='3-4 servings', preparationTime='10 mins', source='', ingredients='quantities to taste', directions='Blend together raspberries, almond milk, banana, and a scoop of almond butter until smooth. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Thai Peanut Noodle Salad', description='A quick and easy meal, perfect for busy weekdays.', servings='2 servings', preparationTime='30 mins', source='', ingredients='as desired', directions='Toss cooked noodles with a Thai peanut sauce, sliced red bell peppers, cabbage, carrots, and cilantro. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Classic Margherita Pizza', description='A quick and easy meal, perfect for busy weekdays.', servings='3-4 servings', preparationTime='30 mins', source='', ingredients='n/a', directions='Spread pizza dough with tomato sauce, top with slices of mozzarella cheese and fresh basil leaves. Bake until crust is golden. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='BBQ Chicken Quesadillas', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='6 servings', preparationTime='2 hrs', source='', ingredients='see directions', directions='Mix shredded cooked chicken with BBQ sauce. Place on tortillas with cheese, fold and cook until crispy. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1)], 'text_representation_type': 'csv', 'seed': 30}
  task = task_obj(params)
  
  open('tmp/code.txt', 'w').write(code)
  open('tmp/app_name.txt', 'w').write('broccoli')
  
  agent = code_agent.CodeAgent(env, save_dir, [task.name])
  agent.FREEZED_CODE = True
  agent.MAX_RETRY_TIMES = 1 # only execute once for code script
  
  def run_episode(task):
    return episode_runner.run_episode(
      goal=task.goal,
      agent=agent,
      max_n_steps=int(10 * task.complexity),
      start_on_home_screen=True,
      termination_fn=None
    )
  
  result = suite_utils._run_task(
    task,
    run_episode,
    env,
    False
  )
  print(f'{result["is_successful"]=}')
  
  open(f'{save_dir}/task_info.txt', 'w').write(str(task.__dict__))
  open(f'{save_dir}/result.txt', 'w').write(f'{result["is_successful"]}' + '\n' + str(result))
  
  env.close()
  return result["is_successful"]

def test_dependency_code(path: int, is_fixed: bool = True):
  '''
  RecipeDeleteDuplicateRecipes
  it's a very easy dependency.
  '''
  task_obj = RecipeDeleteDuplicateRecipes
  code = """\
# task: Delete all but one of any recipes in the Broccoli app that are exact duplicates, ensuring at least one instance of each unique recipe remains
done = False
while not done:
  current_recipes = $main_screen__recipe_card_list
  seen_recipes = set()
  current_done = True
  for i in range(len(current_recipes)):
    recipe = current_recipes[i]
    title = recipe.get_text($main_screen__recipe_card_title)
    description = recipe.get_text($main_screen__recipe_card_description)
    if (title, description) in seen_recipes:
      tap(recipe.match(title))
      # tap($recipe_details_screen__more_options_button) # could fix by dependency
      tap($recipe_details_more_options_popup__delete_button)
      tap($delete_confirmation_dialog__delete_button)
      current_done = False
      break
      # slide effect, delete one element will change the layout
    else:
      seen_recipes.add((title, description))

  if current_done:
    is_to_bottom = scroll($main_screen__recipe_card_list, "down")
    if is_to_bottom:
      done = True
"""

  env = env_launcher.load_and_setup_env(
    console_port=5554,
    emulator_setup=False,
    adb_path=_find_adb_directory(),
  )
  env_launcher.verify_api_level(env)
  
  save_dir = path
  if os.path.exists(save_dir):
    import shutil
    shutil.rmtree(save_dir)
  os.makedirs(save_dir)

  if is_fixed:
    params = {'row_objects': [Recipe(title='Chicken Alfredo Pasta', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='45 mins', source='', ingredients='adjustable', directions='Cook fettuccine pasta, toss with Alfredo sauce and grilled chicken strips. Serve with a sprinkle of Parmesan cheese. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chicken Alfredo Pasta', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='45 mins', source='', ingredients='adjustable', directions='Cook fettuccine pasta, toss with Alfredo sauce and grilled chicken strips. Serve with a sprinkle of Parmesan cheese. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1)], 'noise_row_objects': [Recipe(title='Chicken Caesar Salad Wrap', description='A delicious and healthy choice for any time of the day.', servings='1 serving', preparationTime='1 hrs', source='', ingredients='to your liking', directions='Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Butternut Squash Soup', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='1 serving', preparationTime='45 mins', source='', ingredients='see directions', directions='Sauté onions and garlic, add cubed butternut squash and broth. Puree until smooth and season with nutmeg, salt, and pepper. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Caprese Salad Skewers', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='3 hrs', source='', ingredients='as per recipe', directions='Thread cherry tomatoes, basil leaves, and mozzarella balls onto skewers. Drizzle with balsamic glaze. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Beef Stir Fry', description='A quick and easy meal, perfect for busy weekdays.', servings='8 servings', preparationTime='20 mins', source='', ingredients='optional ingredients', directions='Stir-fry beef slices with broccoli, bell peppers, and onions in soy sauce and garlic. Serve over rice or noodles. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chickpea Vegetable Soup', description='A delicious and healthy choice for any time of the day.', servings='2 servings', preparationTime='30 mins', source='', ingredients='as desired', directions='Sauté onions, carrots, and celery, add broth, canned tomatoes, and chickpeas. Simmer with spinach and seasonings. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1)], 'seed': 30}
  else:
    params = task_obj.generate_random_params()
    params['seed'] = 30
  task = task_obj(params)
  
  open('tmp/code.txt', 'w').write(code)
  open('tmp/app_name.txt', 'w').write('broccoli')
  
  agent = code_agent.CodeAgent(env, save_dir, [task.name])
  agent.FREEZED_CODE = True
  agent.MAX_RETRY_TIMES = 1 # only execute once for code script
  
  def run_episode(task):
    return episode_runner.run_episode(
      goal=task.goal,
      agent=agent,
      max_n_steps=int(10 * task.complexity),
      start_on_home_screen=True,
      termination_fn=None
    )
  
  result = suite_utils._run_task(
    task,
    run_episode,
    env,
    False
  )
  print(f'{result["is_successful"]=}')
  
  open(f'{save_dir}/task_info.txt', 'w').write(str(task.__dict__))
  open(f'{save_dir}/result.txt', 'w').write(f'is_successful={result["is_successful"]}\n{is_fixed=}\n' + str(result))
  
  env.close()
  return result["is_successful"]

def test_bug_processor_code(path: str):
  '''
  RecipeDeleteDuplicateRecipes
  '''
  task_obj = RecipeDeleteDuplicateRecipes
  code = """\
def delete_recipe(recipe_name):
    # Search for the recipe
    tap(elements['search_button'])
    set_text(elements['search_input'], recipe_name)
    
    # Get the list of recipe cards
    recipe_cards = elements['recipe_card_list']

    for i in range(len(recipe_cards)):
        card_title = recipe_cards[i].get_text(elements['recipe_card_title'])
        if card_title == recipe_name:
            recipe_cards[i].tap(elements['recipe_card_title'])
            
            # Open more options and delete the recipe
            tap(elements['recipe_more_options_button'])
            tap(elements['delete_button'])
            tap(elements['delete_confirmation_button'])
            break

    # Clear search and collapse the search bar
    tap(elements['clear_query_button'])
    tap(elements['collapse_button'])

# Recipe names to delete
target_recipes = ["Zucchini Noodles with Pesto", "Garlic Butter Shrimp", "Lentil Soup"]

# Invoke the delete function for each recipe
for recipe in target_recipes:
    delete_recipe(recipe)
"""

  env = env_launcher.load_and_setup_env(
    console_port=5554,
    emulator_setup=False,
    adb_path=_find_adb_directory(),
  )
  env_launcher.verify_api_level(env)
  
  save_dir = path
  if os.path.exists(save_dir):
    import shutil
    shutil.rmtree(save_dir)
  os.makedirs(save_dir)

  params = {'row_objects': [Recipe(title='Chicken Alfredo Pasta', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='45 mins', source='', ingredients='adjustable', directions='Cook fettuccine pasta, toss with Alfredo sauce and grilled chicken strips. Serve with a sprinkle of Parmesan cheese. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chicken Alfredo Pasta', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='45 mins', source='', ingredients='adjustable', directions='Cook fettuccine pasta, toss with Alfredo sauce and grilled chicken strips. Serve with a sprinkle of Parmesan cheese. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1)], 'noise_row_objects': [Recipe(title='Chicken Caesar Salad Wrap', description='A delicious and healthy choice for any time of the day.', servings='1 serving', preparationTime='1 hrs', source='', ingredients='to your liking', directions='Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Butternut Squash Soup', description='An ideal recipe for experimenting with different flavors and ingredients.', servings='1 serving', preparationTime='45 mins', source='', ingredients='see directions', directions='Sauté onions and garlic, add cubed butternut squash and broth. Puree until smooth and season with nutmeg, salt, and pepper. Garnish with fresh herbs for a more vibrant taste.', favorite=0, imageName='', recipeId=-1), Recipe(title='Caprese Salad Skewers', description='A delicious and healthy choice for any time of the day.', servings='3-4 servings', preparationTime='3 hrs', source='', ingredients='as per recipe', directions='Thread cherry tomatoes, basil leaves, and mozzarella balls onto skewers. Drizzle with balsamic glaze. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1), Recipe(title='Beef Stir Fry', description='A quick and easy meal, perfect for busy weekdays.', servings='8 servings', preparationTime='20 mins', source='', ingredients='optional ingredients', directions='Stir-fry beef slices with broccoli, bell peppers, and onions in soy sauce and garlic. Serve over rice or noodles. Try adding a pinch of your favorite spices for extra flavor.', favorite=0, imageName='', recipeId=-1), Recipe(title='Chickpea Vegetable Soup', description='A delicious and healthy choice for any time of the day.', servings='2 servings', preparationTime='30 mins', source='', ingredients='as desired', directions='Sauté onions, carrots, and celery, add broth, canned tomatoes, and chickpeas. Simmer with spinach and seasonings. Feel free to substitute with ingredients you have on hand.', favorite=0, imageName='', recipeId=-1)], 'seed': 30}
  task = task_obj(params)
  
  open('tmp/code.txt', 'w').write(code)
  open('tmp/app_name.txt', 'w').write('broccoli')
  
  agent = code_agent.CodeAgent(env, save_dir, [task.name])
  agent.FREEZED_CODE = True
  agent.MAX_RETRY_TIMES = 2
  
  def run_episode(task):
    return episode_runner.run_episode(
      goal=task.goal,
      agent=agent,
      max_n_steps=int(10 * task.complexity),
      start_on_home_screen=True,
      termination_fn=None
    )
  
  result = suite_utils._run_task(
    task,
    run_episode,
    env,
    False
  )
  print(f'{result["is_successful"]=}')
  
  open(f'{save_dir}/task_info.txt', 'w').write(str(task.__dict__))
  open(f'{save_dir}/result.txt', 'w').write(f'{result["is_successful"]}' + '\n' + str(result))
  
  env.close()
  return result["is_successful"]

if __name__ == "__main__":
  count = 0
  total = 0
  batch_size = 1
  fail_path = []
  
  # test_correct_code
  path = 'unit_test/test_correct_code'
  for i in range(batch_size):
    _path = f'{path}/{i}'
    res = test_correct_code(_path, False)
    if res != 1:
      fail_path.append(_path)
    count += res
  total += batch_size
  
  for i in range(batch_size):
    _path = f'{path}/{i}_f'
    res = test_correct_code(_path, True)
    if res != 1:
      fail_path.append(_path)
    count += res
  total += batch_size
  
  print(f'acc: {count}/{total}')
  
  # test_correct_code1
  path = 'unit_test/test_correct_code1'
  for i in range(batch_size):
    _path = f'{path}/{i}'
    res = test_correct_code1(_path)
    if res != 1:
      fail_path.append(_path)
    count += res
  total += batch_size
  
  print(f'acc: {count}/{total}')
  
  # test_dependency_code
  path = 'unit_test/test_dependency_code'
  for i in range(batch_size):
    _path = f'{path}/{i}'
    res = test_dependency_code(_path, False)
    if res != 1:
      fail_path.append(_path)
    count += res
  total += batch_size
  
  for i in range(batch_size):
    _path = f'{path}/{i}_f'
    res = test_dependency_code(_path, True)
    if res != 1:
      fail_path.append(_path)
    count += res
  total += batch_size
  
  print(f'acc: {count}/{total}')
  
  # test_bug_processor_code
  path = 'unit_test/test_bug_processor_code'
  for i in range(batch_size):
    _path = f'{path}/{i}'
    res = test_bug_processor_code(_path)
    if res != 1.0:
      fail_path.append(_path)
    count += res
  total += batch_size
  
  print(f'acc: {count}/{total}')
  
  result = {
    'fail_paths': fail_path,
    'acc': count / total
  }
  
  print(fail_path)
  json.dump(result, open('unit_test/result.json', 'w'), indent=2)
  