I want to build a command line shopping_agent for workshop purpose. Before the workshop I want to create a sample shopping agent that can do the following:

1. wait for my instruction which is two types: a. ask for the items avaiable for shopping. b. ask it to buy some items
2. for a, it will return a list of items with unit prices
3. for b, it will check the items it has (in its catalog), and find the matching items and then create an order and then present it to me for review (in text format, no web ui). I will either give it approval or rejection.
4. if I give it the approval, it should just checkout, pay and schedule the shipping (delivery); the payment and shipping part would be fake for demo purpose, and agent should then give me the order in the format of a pdf file.
5. if I reject it, the agent should say the order is canceled and back to wait for my instruction.

The above agent should be build in the subfolder initial.
